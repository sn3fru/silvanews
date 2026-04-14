"""
Estagiário v3 — Executor com Gemini Function Calling nativo + self-critique.

Arquitetura:
  1. Monta prompt com system instructions + pergunta do usuário.
  2. Loop de function calling (Gemini nativo): generate → dispatch → FunctionResponse → repeat.
  3. Quando o LLM emite texto (sem function_call): extrai resposta final.
  4. Self-critique: avalia qualidade da resposta (nota 1-5). Se < 4, re-prompta com feedback (max 2 retries).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional, Callable, Dict, Any

try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # type: ignore

try:
    from backend.database import SessionLocal
except Exception:
    SessionLocal = None  # type: ignore

from .tools.definitions import build_tool_declarations, dispatch_tool
from .prompts import ESTAGIARIO_SYSTEM_PROMPT_V3, PROMPT_CRITIQUE_V1

_MAX_ITERATIONS = 15
_MAX_TOOL_CALLS = 10
_MAX_CRITIQUE_RETRIES = 2
_MAX_OUTPUT_TOKENS = 16384
_GEMINI_MODEL = "gemini-2.0-flash"
_TAG = "[Estagiario]"

_STEP_LABELS = {
    "list_cluster_titles": "Lendo títulos das notícias...",
    "query_clusters": "Buscando clusters com filtros...",
    "get_cluster_details": "Aprofundando notícia...",
    "query_clusters_range": "Buscando notícias em múltiplos dias...",
    "obter_textos_brutos_cluster": "Lendo textos originais...",
    "buscar_na_web": "Pesquisando na web...",
}


def _open_db():
    if SessionLocal is None:
        raise RuntimeError("Backend indisponível")
    return SessionLocal()


def _init_genai():
    if genai is None:
        raise RuntimeError("google-generativeai não instalado.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definida no ambiente.")
    genai.configure(api_key=api_key)
    return genai


class EstagiarioExecutor:
    """Executor v3 — Gemini function calling + self-critique loop."""

    def run(
        self,
        user_input: str,
        chat_history: List[str] | None = None,
        data_referencia: str = "",
        on_step: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        Main entry point. Returns {"final": str, "trace": list}.
        """
        chat_history = chat_history or []
        trace: List[Dict[str, Any]] = []
        t0 = time.time()

        try:
            _genai = _init_genai()
        except RuntimeError as e:
            return {"final": f"Erro: {e}", "trace": trace}

        prompt_text = ESTAGIARIO_SYSTEM_PROMPT_V3.format(
            data_referencia=data_referencia or "hoje",
            chat_history="\n".join(chat_history) if chat_history else "(sem histórico)",
            pergunta=user_input,
        )

        tool_declaration = build_tool_declarations()
        model = _genai.GenerativeModel(_GEMINI_MODEL, tools=[tool_declaration])

        db = _open_db()
        try:
            raw_answer = self._function_calling_loop(
                _genai, model, db, prompt_text, trace, on_step,
            )
        finally:
            try:
                db.close()
            except Exception:
                pass

        if not raw_answer:
            return {
                "final": "Não consegui gerar uma resposta. Tente reformular a pergunta.",
                "trace": trace,
            }

        final_answer = self._self_critique_loop(
            _genai, user_input, raw_answer, trace, on_step,
        )

        elapsed = time.time() - t0
        print(f"{_TAG} Concluído em {elapsed:.1f}s, {len(trace)} steps")
        return {"final": final_answer, "trace": trace}

    # ──────────────────────────────────────────────────────────
    # Function Calling Loop (mirrors resumo_diario _run_llm_with_tools)
    # ──────────────────────────────────────────────────────────

    def _function_calling_loop(
        self,
        _genai,
        model,
        db,
        prompt_text: str,
        trace: list,
        on_step: Optional[Callable],
    ) -> Optional[str]:
        print(f"{_TAG} Enviando ao LLM ({len(prompt_text)} chars, budget={_MAX_TOOL_CALLS})...")

        response = model.generate_content(
            prompt_text,
            generation_config={"temperature": 0.3, "max_output_tokens": _MAX_OUTPUT_TOKENS},
        )

        tool_calls_used = 0

        for iteration in range(_MAX_ITERATIONS):
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None:
                print(f"{_TAG} Sem candidatos na iteração {iteration + 1}.")
                return None

            parts = candidate.content.parts
            has_fc = any(hasattr(p, "function_call") and p.function_call.name for p in parts)

            if not has_fc:
                text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                final = "\n".join(text_parts).strip()
                print(f"{_TAG} Resposta recebida ({len(final)} chars, {tool_calls_used} tool calls)")
                trace.append({"type": "answer", "chars": len(final), "tool_calls": tool_calls_used})
                return final

            function_responses = []
            for part in parts:
                if not (hasattr(part, "function_call") and part.function_call.name):
                    continue

                fc = part.function_call
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}
                tool_calls_used += 1

                if on_step:
                    label = _STEP_LABELS.get(fn_name, f"Executando {fn_name}...")
                    on_step(label)

                if tool_calls_used > _MAX_TOOL_CALLS:
                    print(f"{_TAG}   [BUDGET] Limite atingido ({_MAX_TOOL_CALLS}).")
                    result_data = {"error": "Limite de ferramentas atingido. Redija a resposta final agora."}
                else:
                    print(f"{_TAG}   [TOOL {tool_calls_used}/{_MAX_TOOL_CALLS}] {fn_name}({_summarize_args(fn_args)})")
                    try:
                        result_data = dispatch_tool(db, fn_name, fn_args)
                    except Exception as e:
                        result_data = {"error": str(e)}
                    result_json = json.dumps(result_data, ensure_ascii=False, default=str)
                    print(f"{_TAG}   [TOOL {tool_calls_used}/{_MAX_TOOL_CALLS}] → {len(result_json)} chars")

                trace.append({
                    "type": "tool_call",
                    "tool": fn_name,
                    "args": fn_args,
                    "iteration": iteration + 1,
                })

                function_responses.append(
                    _genai.protos.Part(
                        function_response=_genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": json.dumps(result_data, ensure_ascii=False, default=str)},
                        )
                    )
                )

            print(f"{_TAG}   Reenviando com {len(function_responses)} respostas de tool...")
            response = model.generate_content(
                [
                    _genai.protos.Content(role="user", parts=[_genai.protos.Part(text=prompt_text)]),
                    candidate.content,
                    _genai.protos.Content(role="function", parts=function_responses),
                ],
                generation_config={"temperature": 0.3, "max_output_tokens": _MAX_OUTPUT_TOKENS},
            )

        print(f"{_TAG} Limite de iterações atingido ({_MAX_ITERATIONS}).")
        return None

    # ──────────────────────────────────────────────────────────
    # Self-Critique Loop
    # ──────────────────────────────────────────────────────────

    def _self_critique_loop(
        self,
        _genai,
        pergunta: str,
        resposta: str,
        trace: list,
        on_step: Optional[Callable],
    ) -> str:
        """Evaluate answer quality. If poor, re-prompt with feedback (max retries)."""
        model_critic = _genai.GenerativeModel(_GEMINI_MODEL)
        current = resposta

        for attempt in range(_MAX_CRITIQUE_RETRIES):
            critique_prompt = PROMPT_CRITIQUE_V1.format(
                pergunta=pergunta,
                resposta=current,
            )
            try:
                resp = model_critic.generate_content(
                    critique_prompt,
                    generation_config={"temperature": 0.1, "max_output_tokens": 512},
                )
                raw = (resp.text or "").strip()
                evaluation = _parse_critique(raw)
            except Exception as e:
                print(f"{_TAG} Critique falhou: {e}")
                break

            nota = evaluation.get("nota", 5)
            feedback = evaluation.get("feedback", "OK")
            trace.append({"type": "critique", "attempt": attempt + 1, "nota": nota, "feedback": feedback})
            print(f"{_TAG} Critique #{attempt + 1}: nota={nota}, feedback={feedback[:80]}")

            if nota >= 4:
                break

            if on_step:
                on_step("Refinando resposta...")

            retry_prompt = (
                f"Sua resposta anterior recebeu nota {nota}/5. Feedback: {feedback}\n\n"
                f"Pergunta original: {pergunta}\n\n"
                f"Resposta anterior:\n{current}\n\n"
                "Reescreva a resposta corrigindo os pontos indicados. "
                "Mantenha o formato Markdown e inclua dados específicos."
            )
            try:
                resp2 = model_critic.generate_content(
                    retry_prompt,
                    generation_config={"temperature": 0.3, "max_output_tokens": _MAX_OUTPUT_TOKENS},
                )
                improved = (resp2.text or "").strip()
                if improved and len(improved) > len(current) * 0.5:
                    current = improved
                    trace.append({"type": "retry", "attempt": attempt + 1, "chars": len(improved)})
                    print(f"{_TAG} Resposta melhorada ({len(improved)} chars)")
            except Exception as e:
                print(f"{_TAG} Retry falhou: {e}")
                break

        return current


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _parse_critique(raw: str) -> dict:
    m = re.search(r"\{[^}]*\"nota\"\s*:", raw)
    if m:
        brace_start = m.start()
        depth, end = 0, brace_start
        for i in range(brace_start, len(raw)):
            if raw[i] == '{':
                depth += 1
            elif raw[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            return json.loads(raw[brace_start:end])
        except json.JSONDecodeError:
            pass
    return {"nota": 5, "feedback": "OK"}


def _summarize_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 40:
            s = s[:37] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
