from __future__ import annotations

"""
Agente 'Estagiário' v3 — Pesquisa inteligente sobre notícias via Gemini Function Calling.

Delega ao EstagiarioExecutor (function calling loop + self-critique).
Interface pública: answer(), answer_with_context().
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime

try:
    from backend.utils import get_date_brasil
except Exception:
    from datetime import date as _date
    get_date_brasil = _date.today


@dataclass
class AgentAnswer:
    ok: bool
    text: str
    data: Optional[Dict[str, Any]] = None


class EstagiarioAgent:
    """Agente de pesquisa sobre notícias — delega ao executor v3."""

    def __init__(self) -> None:
        print("[Estagiario] v3 inicializado")

    def answer_with_context(
        self,
        question: str,
        chat_history: List[Dict[str, Any]],
        date_str: Optional[str] = None,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> AgentAnswer:
        """Responde perguntas mantendo o contexto da conversa anterior."""
        history_lines: List[str] = []
        if chat_history and len(chat_history) > 1:
            for msg in chat_history[:-1]:
                role = "Usuário" if msg.get("role") == "user" else "Assistente"
                content = (msg.get("content", "") or "")[:500]
                history_lines.append(f"{role}: {content}")

        return self.answer(question, date_str, history_lines=history_lines, on_step=on_step)

    def answer(
        self,
        question: str,
        date_str: Optional[str] = None,
        history_lines: List[str] | None = None,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> AgentAnswer:
        """Responde perguntas via executor v3 (Gemini function calling + self-critique)."""
        print(f"[Estagiario] === ANSWER v3 === Pergunta: {question}")

        target_date = None
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                target_date = get_date_brasil()
        if target_date is None:
            target_date = get_date_brasil()

        try:
            from .executor import EstagiarioExecutor

            executor = EstagiarioExecutor()
            out = executor.run(
                user_input=question,
                chat_history=history_lines or [],
                data_referencia=target_date.isoformat(),
                on_step=on_step,
            )
            final = out.get("final") or "Não foi possível gerar uma resposta."
            trace = out.get("trace") or []
            print(f"[Estagiario] v3 concluído: {len(trace)} steps")
            return AgentAnswer(True, final, {"react_trace": trace})
        except Exception as e:
            print(f"[Estagiario] Falha executor v3: {e}")
            import traceback
            traceback.print_exc()
            return AgentAnswer(False, f"Erro interno do estagiário: {e}")
