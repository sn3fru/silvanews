"""
Agente de Resumo Diário — Chamada Unificada + Per-User

Arquitetura v3.0:
  1. CONTEXTO: _build_context_block() recolhe TODOS os clusters do dia UMA VEZ.
  2. MODO PADRÃO: 1 chamada LLM unificada (cobre distressed+regulatorio+estrategico).
     O LLM recebe todos os titulos+resumos e decide onde aprofundar via tools.
     Custo: 1 chamada LLM + ate 5 tool calls (vs. 3 chamadas do modelo antigo).
  3. MODO PER-USER: 1 chamada LLM por usuario com preferencias personalizadas.
  4. VALIDAÇÃO: JSON → Pydantic → fallback.
  5. FORMATAÇÃO: WhatsApp / terminal, agrupada por seção temática.

READ-ONLY — não altera banco. Prioridade P1/P2/P3 é GLOBAL, nunca mutada.
"""

from __future__ import annotations

import json
import os
import re
import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from backend.database import SessionLocal, ClusterEvento
    from backend.crud import (
        get_clusters_for_feed_by_date,
        get_preferencias_usuario,
        get_template_resumo,
    )
    from backend.utils import get_date_brasil
    from backend.prompts import (
        PROMPT_CORRECAO_PYDANTIC_V1,
    )
except Exception:
    SessionLocal = None  # type: ignore
    ClusterEvento = None  # type: ignore
    get_clusters_for_feed_by_date = None  # type: ignore
    get_preferencias_usuario = None  # type: ignore
    get_template_resumo = None  # type: ignore
    get_date_brasil = None  # type: ignore
    PROMPT_CORRECAO_PYDANTIC_V1 = ""  # type: ignore

from agents.resumo_diario.tools.definitions import (
    ResumoDiarioContract,
    TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA,
    TOOL_BUSCAR_NA_WEB_SCHEMA,
    execute_obter_textos_brutos,
    execute_buscar_na_web,
)

_MAX_TOOL_CALLS = 5       # chamada unificada: permite aprofundamento seletivo
_MAX_TOOL_CALLS_USER = 8  # per-user: triagem + deep-dive em P1/P2 selecionados
_MAX_ITERATIONS = 10      # acomoda tool-calling loop

# Cache de contexto com invalidacao por updated_at de clusters_eventos
_CONTEXT_CACHE: Dict[str, Any] = {}

# --------------------------------------------------------------------------- #
# HELPERS
# --------------------------------------------------------------------------- #

def _open_db():
    """Abre sessão do banco de dados."""
    if SessionLocal is None:
        raise RuntimeError("Backend indisponível — SessionLocal não configurado.")
    return SessionLocal()


def _truncate_resumo_p3(resumo: Optional[str], max_chars: int = 120) -> str:
    """Retorna apenas a primeira frase do resumo (para P3 — contexto curto)."""
    if not resumo:
        return ""
    for sep in [". ", ".\n", ".\r"]:
        idx = resumo.find(sep)
        if 0 < idx <= max_chars:
            return resumo[: idx + 1]
    return resumo[:max_chars].rstrip() + ("..." if len(resumo) > max_chars else "")


# --------------------------------------------------------------------------- #
# ETAPA 1: MAP-REDUCE — Montar contexto do dia (executado UMA VEZ)
# --------------------------------------------------------------------------- #

def _build_tipo_fonte_map(db, target_date: datetime.date) -> Dict[int, str]:
    """Busca tipo_fonte diretamente do ORM (campo não exposto pelo CRUD feed)."""
    try:
        from sqlalchemy import func
        rows = db.query(ClusterEvento.id, ClusterEvento.tipo_fonte).filter(
            func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == 'ativo',
        ).all()
        return {r.id: (r.tipo_fonte or 'nacional') for r in rows}
    except Exception as e:
        print(f"[ResumoDiario] Falha ao buscar tipo_fonte do ORM: {e}")
        return {}


def _build_context_block(db, target_date: datetime.date) -> Tuple[str, List[int], Dict[int, List[str]]]:
    """
    Recolhe TODOS os clusters ativos do dia (P1, P2, P3), todas as fontes,
    e monta um bloco de texto estruturado para injeção nos prompts.
    Executado UMA ÚNICA VEZ — o resultado é partilhado entre todas as personas.

    Returns:
        (contexto_str, lista_cluster_ids, fontes_map)
        fontes_map: {cluster_id: ["Folha de S.Paulo", "Valor Econômico", ...]}
    """
    print(f"[ResumoDiario] Construindo contexto para {target_date.isoformat()}")

    clusters_all: List[Dict[str, Any]] = []
    avaliados_ids: List[int] = []

    page = 1
    while True:
        resp = get_clusters_for_feed_by_date(
            db, target_date, page=page, page_size=100, load_full_text=False
        )
        batch = resp.get("clusters", [])
        clusters_all.extend(batch)
        if not resp.get("paginacao", {}).get("tem_proxima"):
            break
        page += 1

    print(f"[ResumoDiario] Total de clusters carregados: {len(clusters_all)}")

    if not clusters_all:
        return "(Nenhum cluster encontrado para esta data.)", [], {}

    tipo_fonte_map = _build_tipo_fonte_map(db, target_date)
    fontes_map: Dict[int, List[str]] = {}  # cluster_id -> [nomes de jornais]

    linhas: List[str] = []
    for c in clusters_all:
        cid = c.get("id")
        if cid is None:
            continue
        avaliados_ids.append(cid)
        prio = c.get("prioridade", "P3_MONITORAMENTO")
        titulo = c.get("titulo_final", "Sem título")
        resumo_raw = c.get("resumo_final", "")
        tag = c.get("tag", "")
        total_artigos = c.get("total_artigos", 0)

        try:
            from backend.utils import normalizar_fonte_display
        except ImportError:
            normalizar_fonte_display = lambda x: x  # type: ignore

        raw_fontes = c.get("fontes", [])
        nomes_fontes = []
        if isinstance(raw_fontes, list):
            for f in raw_fontes:
                raw_name = ""
                if isinstance(f, dict):
                    raw_name = (f.get("nome") or "").strip()
                elif isinstance(f, str):
                    raw_name = f.strip()
                clean = normalizar_fonte_display(raw_name)
                if clean:
                    nomes_fontes.append(clean)

        seen_fontes = set()
        nomes_fontes_unique = []
        for fn in nomes_fontes:
            if fn.lower() not in seen_fontes:
                seen_fontes.add(fn.lower())
                nomes_fontes_unique.append(fn)
        fontes_map[cid] = nomes_fontes_unique
        fontes_label = ", ".join(nomes_fontes_unique[:3]) if nomes_fontes_unique else "Fonte não identificada"

        if prio in ("P1_CRITICO", "P2_ESTRATEGICO"):
            resumo = resumo_raw
        else:
            resumo = _truncate_resumo_p3(resumo_raw)

        tipo_fonte = tipo_fonte_map.get(cid, "")

        linhas.append(
            f"[ID={cid}] [{prio}] [{tag}] [{tipo_fonte}] "
            f"(Fontes: {fontes_label})\n"
            f"  Título: {titulo}\n"
            f"  Resumo: {resumo}\n"
        )

    # Calculo de temperatura cruzada (volume x diversidade de tags)
    p1_count = sum(1 for c in clusters_all if c.get("prioridade") == "P1_CRITICO")
    p2_count = sum(1 for c in clusters_all if c.get("prioridade") == "P2_ESTRATEGICO")
    p3_count = sum(1 for c in clusters_all if c.get("prioridade") == "P3_MONITORAMENTO")
    tags_distintas = set()
    for c in clusters_all:
        tag_val = c.get("tag", "")
        if tag_val:
            tags_distintas.add(tag_val)
    n_tags = len(tags_distintas)
    total = len(clusters_all)

    if (p1_count + p2_count >= 5) and n_tags >= 3:
        temperatura = "QUENTE"
    elif p1_count + p2_count >= 2:
        temperatura = "MORNO"
    else:
        temperatura = "FRIO"

    header_temperatura = (
        f"\n--- CONTEXTO DO DIA ---\n"
        f"TEMPERATURA DO DIA: {temperatura}\n"
        f"Estatísticas: {p1_count} P1, {p2_count} P2, {p3_count} P3 (Total: {total} clusters)\n"
        f"Diversidade de tags: {n_tags} tags distintas ({', '.join(sorted(tags_distintas))})\n"
        f"\nREGRAS DE CURADORIA ADAPTATIVA:\n"
        f"- DIA QUENTE: Seja RIGOROSO. Selecione 7-12 itens mais impactantes.\n"
        f"- DIA MORNO: Selecione P1+P2 e complemente com os melhores P3. 5-8 itens.\n"
        f"- DIA FRIO: Baixe a régua. Selecione os P3 mais relevantes (3-5 itens).\n"
        f"- NUNCA retorne 0 itens. Sempre há algo a reportar.\n"
        f"--- FIM CONTEXTO ---\n\n"
    )

    contexto = header_temperatura + "\n".join(linhas)
    print(f"[ResumoDiario] Contexto montado: {len(contexto)} chars, {len(avaliados_ids)} clusters, temperatura={temperatura}")
    return contexto, avaliados_ids, fontes_map


# --------------------------------------------------------------------------- #
# ETAPA 2: INTERAÇÃO COM O LLM (Gemini + Function Calling)
# --------------------------------------------------------------------------- #

def _extract_json_from_text(text: str) -> Optional[dict]:
    """Extrai o primeiro objeto JSON válido de uma string (com fallbacks)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _run_llm_with_tools(
    db,
    prompt_text: str,
    persona_name: str = "",
    tool_call_budget: int = _MAX_TOOL_CALLS,
) -> Optional[str]:
    """
    Chama Gemini com o prompt e a tool `obter_textos_brutos_cluster`.
    Cada persona recebe sua própria sessão de banco e budget de tools.
    """
    import google.generativeai as genai  # type: ignore

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não definida no ambiente.")

    genai.configure(api_key=api_key)

    tag = f"[{persona_name}]" if persona_name else "[ResumoDiario]"

    # Se budget=0, nao registra tools (chamada direta — mais barata e rapida)
    if tool_call_budget > 0:
        tool_declaration = genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA["name"],
                    description=TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "cluster_id": genai.protos.Schema(
                                type=genai.protos.Type.INTEGER,
                                description=TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA["parameters"]["properties"]["cluster_id"]["description"],
                            )
                        },
                        required=["cluster_id"],
                    ),
                ),
                genai.protos.FunctionDeclaration(
                    name=TOOL_BUSCAR_NA_WEB_SCHEMA["name"],
                    description=TOOL_BUSCAR_NA_WEB_SCHEMA["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            "query": genai.protos.Schema(
                                type=genai.protos.Type.STRING,
                                description=TOOL_BUSCAR_NA_WEB_SCHEMA["parameters"]["properties"]["query"]["description"],
                            )
                        },
                        required=["query"],
                    ),
                ),
            ]
        )
        model = genai.GenerativeModel("gemini-2.0-flash", tools=[tool_declaration])
    else:
        model = genai.GenerativeModel("gemini-2.0-flash")

    print(f"{tag} Enviando contexto ao LLM ({len(prompt_text)} chars, tools={'sim' if tool_call_budget > 0 else 'nao'}, budget={tool_call_budget})...")

    response = model.generate_content(
        prompt_text,
        generation_config={"temperature": 0.2, "max_output_tokens": 8192},
    )

    tool_calls_used = 0
    iterations = 0
    import time as _t
    t0 = _t.time()

    while iterations < _MAX_ITERATIONS:
        iterations += 1
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None:
            print(f"{tag} Sem candidatos na resposta do LLM.")
            return None

        parts = candidate.content.parts
        has_function_call = any(hasattr(p, "function_call") and p.function_call.name for p in parts)

        if not has_function_call:
            text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
            final_text = "\n".join(text_parts).strip()
            elapsed = _t.time() - t0
            print(f"{tag} Resposta final recebida ({len(final_text)} chars, {tool_calls_used} tool calls, {elapsed:.1f}s)")
            return final_text

        function_responses = []
        for part in parts:
            if not (hasattr(part, "function_call") and part.function_call.name):
                continue

            fc = part.function_call
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}

            if fn_name == "obter_textos_brutos_cluster":
                cluster_id = int(fn_args.get("cluster_id", 0))
                tool_calls_used += 1

                if tool_calls_used > tool_call_budget:
                    print(f"{tag}   [BUDGET] Limite atingido ({tool_call_budget}). Pedindo JSON final.")
                    result_data = {"error": "Limite de chamadas a ferramentas atingido. Produza o JSON final agora."}
                else:
                    print(f"{tag}   [TOOL {tool_calls_used}/{tool_call_budget}] Aprofundando cluster {cluster_id}...")
                    result_data = execute_obter_textos_brutos(db, cluster_id)
                    n_artigos = len(result_data) if isinstance(result_data, list) else 0
                    chars = sum(len(str(r.get("texto_bruto", ""))) for r in result_data) if isinstance(result_data, list) else 0
                    print(f"{tag}   [TOOL {tool_calls_used}/{tool_call_budget}] Cluster {cluster_id}: {n_artigos} artigos, {chars} chars de texto bruto")

                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": json.dumps(result_data, ensure_ascii=False, default=str)},
                        )
                    )
                )
            elif fn_name == "buscar_na_web":
                query = str(fn_args.get("query", ""))
                tool_calls_used += 1

                if tool_calls_used > tool_call_budget:
                    result_data = {"error": "Limite de chamadas a ferramentas atingido. Produza o JSON final agora."}
                else:
                    print(f"{tag}   [WEB {tool_calls_used}/{tool_call_budget}] Buscando: '{query[:60]}'...")
                    result_data = execute_buscar_na_web(query)
                    n_results = len(result_data.get("results", [])) if isinstance(result_data, dict) else 0
                    print(f"{tag}   [WEB {tool_calls_used}/{tool_call_budget}] {n_results} resultados")

                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": json.dumps(result_data, ensure_ascii=False, default=str)},
                        )
                    )
                )
            else:
                function_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"error": f"Tool '{fn_name}' não reconhecida."},
                        )
                    )
                )

        print(f"{tag}   Reenviando ao LLM com {len(function_responses)} respostas de tool...")
        response = model.generate_content(
            [
                genai.protos.Content(role="user", parts=[genai.protos.Part(text=prompt_text)]),
                candidate.content,
                genai.protos.Content(role="function", parts=function_responses),
            ],
            generation_config={"temperature": 0.2, "max_output_tokens": 8192},
        )

    print(f"{tag} Limite de iteracoes atingido ({_MAX_ITERATIONS}).")
    return None


# --------------------------------------------------------------------------- #
# ETAPA 3: VALIDAÇÃO PYDANTIC + FALLBACK
# --------------------------------------------------------------------------- #

def _validate_and_fix(raw_json_str: str, persona_name: str = "") -> ResumoDiarioContract:
    """
    Valida o JSON do LLM com Pydantic.
    Se falhar (ValidationError), faz UMA chamada fallback ao LLM.
    """
    from pydantic import ValidationError

    tag = f"[{persona_name}]" if persona_name else "[ResumoDiario]"

    data = _extract_json_from_text(raw_json_str)
    if data is None:
        raise ValueError(f"{tag} Impossível extrair JSON: {raw_json_str[:500]}")

    try:
        return ResumoDiarioContract(**data)
    except ValidationError as e:
        erro_str = str(e)
        print(f"{tag} Pydantic ValidationError (tentando fallback): {erro_str[:400]}")

        prompt_correcao = PROMPT_CORRECAO_PYDANTIC_V1.format(
            ERRO_PYDANTIC=erro_str,
            JSON_FALHADO=json.dumps(data, ensure_ascii=False, default=str),
        )

        import google.generativeai as genai  # type: ignore
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY ausente para fallback Pydantic.")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(
            prompt_correcao,
            generation_config={"temperature": 0.1, "max_output_tokens": 4096},
        )
        fixed_text = (resp.text or "").strip()
        print(f"{tag} Fallback Pydantic recebido ({len(fixed_text)} chars)")

        fixed_data = _extract_json_from_text(fixed_text)
        if fixed_data is None:
            raise ValueError(f"{tag} Fallback falhou: {fixed_text[:500]}")

        return ResumoDiarioContract(**fixed_data)


# --------------------------------------------------------------------------- #
# FUNÇÃO PRINCIPAL — 1 chamada LLM unificada (substitui multi-persona)
# --------------------------------------------------------------------------- #

def gerar_resumo_diario(
    target_date: Optional[datetime.date] = None,
    prompt_template: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ponto de entrada do agente de resumo diário (v3 — chamada unificada).

    Fluxo:
      1. Constrói contexto UMA VEZ (_build_context_block) — todos os clusters do dia
      2. Faz 1 chamada LLM com prompt unificado que cobre distressed+regulatorio+estrategico
      3. LLM pode usar tools para aprofundar clusters específicos (budget: 5 calls)
      4. Valida JSON → Pydantic → fallback

    Args:
        target_date: Data para gerar o resumo (padrão: hoje).
        prompt_template: Template de prompt (padrão: PROMPT_RESUMO_UNIFICADO_V1).

    Returns:
        Dict com ok, data, contract_dict, clusters_avaliados_ids, fontes_map, etc.
    """
    if target_date is None:
        target_date = get_date_brasil()

    if prompt_template is None:
        try:
            from backend.prompts import PROMPT_RESUMO_UNIFICADO_V1
            prompt_template = PROMPT_RESUMO_UNIFICADO_V1
        except ImportError:
            return {"ok": False, "data": target_date.isoformat(), "error": "PROMPT_RESUMO_UNIFICADO_V1 não encontrado."}

    print(f"[ResumoDiario] {target_date.isoformat()} — Construindo contexto...")

    # 1. Montar contexto (com cache por updated_at)
    db_ctx = _open_db()
    fontes_map: Dict[int, List[str]] = {}
    try:
        from sqlalchemy import func as sqla_func
        max_updated = db_ctx.query(sqla_func.max(ClusterEvento.updated_at)).filter(
            sqla_func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == 'ativo',
        ).scalar()
        cache_key = f"{target_date.isoformat()}_{max_updated.isoformat() if max_updated else 'empty'}"

        cached = _CONTEXT_CACHE.get(cache_key)
        if cached:
            contexto, avaliados_ids, fontes_map = cached
        else:
            contexto, avaliados_ids, fontes_map = _build_context_block(db_ctx, target_date)
            _CONTEXT_CACHE.clear()
            _CONTEXT_CACHE[cache_key] = (contexto, avaliados_ids, fontes_map)
    finally:
        try:
            db_ctx.close()
        except Exception:
            pass

    if not avaliados_ids:
        return {
            "ok": False,
            "data": target_date.isoformat(),
            "error": "Nenhum cluster encontrado para esta data.",
        }

    print(f"[ResumoDiario] {len(avaliados_ids)} clusters, {len(contexto)} chars de contexto")

    # 2. Montar prompt e chamar LLM (1 chamada unificada, tools habilitadas)
    prompt_final = prompt_template.format(CONTEXTO_CLUSTERS_DIA=contexto)

    db_llm = _open_db()
    try:
        raw_response = _run_llm_with_tools(
            db_llm, prompt_final, persona_name="resumo", tool_call_budget=_MAX_TOOL_CALLS
        )
    finally:
        try:
            db_llm.close()
        except Exception:
            pass

    if not raw_response:
        return {
            "ok": False,
            "data": target_date.isoformat(),
            "error": "LLM não retornou resposta.",
        }

    # 3. Validar JSON → Pydantic
    try:
        contract = _validate_and_fix(raw_response, persona_name="resumo")
    except Exception as e:
        return {
            "ok": False,
            "data": target_date.isoformat(),
            "error": f"Validação Pydantic falhou: {e}",
        }

    escolhidos = [cs.cluster_id for cs in contract.clusters_selecionados]
    secoes: Dict[str, List] = {}
    for cs in contract.clusters_selecionados:
        secoes.setdefault(cs.secao, []).append(cs)

    SECAO_EMOJIS = {"distressed": "💀", "regulatorio": "⚖️", "estrategico": "🏛️", "geral": "📋"}
    print(f"\n{'='*60}")
    print(f"[ResumoDiario] RESULTADO — {len(escolhidos)} itens de {len(avaliados_ids)} clusters")
    print(f"{'='*60}")
    if contract.tldr_executivo:
        print(f"  TL;DR: {contract.tldr_executivo}")
    for secao_key in ["distressed", "regulatorio", "estrategico", "geral"]:
        items = secoes.get(secao_key, [])
        if not items:
            continue
        emoji = SECAO_EMOJIS.get(secao_key, "📋")
        print(f"\n  {emoji} {secao_key.upper()} ({len(items)} itens):")
        for cs in items:
            print(f"    - [{cs.cluster_id}] {cs.titulo_whatsapp}")
            print(f"      {cs.bullet_impacto[:120]}")
    print(f"{'='*60}")

    return {
        "ok": True,
        "data": target_date.isoformat(),
        "contract_dict": contract.model_dump(),
        "clusters_avaliados_ids": avaliados_ids,
        "todos_clusters_escolhidos_ids": sorted(set(escolhidos)),
        "fontes_map": fontes_map,
        "prompt_version": "UNIFICADO_V3",
    }


# --------------------------------------------------------------------------- #
# MODO PER-USER (v3.0): Uma chamada LLM por usuario com contexto compartilhado
# --------------------------------------------------------------------------- #

_PROMPT_USER_TEMPLATE = """Você é um analista de inteligência financeira sênior da mesa de Special Situations do BTG Pactual.
Seu objetivo: produzir um resumo diário PERSONALIZADO de alta qualidade.

VOCÊ OPERA EM 2 FASES OBRIGATÓRIAS:

═══════════════════════════════════════════════════════════
FASE 1 — TRIAGEM (leia o contexto abaixo e selecione candidatos)
═══════════════════════════════════════════════════════════

{CONTEXTO_CLUSTERS_DIA}

PREFERÊNCIAS DO USUÁRIO:
- Tags de foco: {TAGS_FOCO}
- Tags ignoradas: {TAGS_IGNORADAS}
- Tipo de fonte preferido: {TIPO_FONTE}
- Tamanho do resumo: {TAMANHO} itens

INSTRUÇÃO PERSONALIZADA DO TEMPLATE:
{INSTRUCAO_TEMPLATE}

INSTRUÇÕES DA FASE 1:
- Leia TODOS os clusters acima (títulos + resumos curtos).
- Selecione {MIN_ITENS} a {MAX_ITENS} clusters candidatos que são relevantes para o perfil do usuário.
- PRIORIZE clusters cujas tags estejam em "Tags de foco". Se não houver match, use os mais relevantes.
- IGNORE clusters cujas tags estejam em "Tags ignoradas".

═══════════════════════════════════════════════════════════
FASE 2 — APROFUNDAMENTO (use a tool para enriquecer os selecionados)
═══════════════════════════════════════════════════════════

Após selecionar os candidatos na Fase 1:
- Para CADA cluster P1_CRITICO e P2_ESTRATEGICO selecionado, use OBRIGATORIAMENTE a tool
  `obter_textos_brutos_cluster(cluster_id)` para acessar dados factuais completos (valores, nomes,
  datas, varas judiciais, montantes). O resumo curto do contexto NÃO contém esses dados.
- Para clusters P3_MONITORAMENTO, o aprofundamento é OPCIONAL (use apenas se o resumo parecer vago).
- Use também `buscar_na_web(query)` se precisar de informação complementar atualizada (max 2 buscas).
- NÃO invente dados factuais. Se a tool não retornar o dado, escreva sem ele.

═══════════════════════════════════════════════════════════
RESPOSTA FINAL
═══════════════════════════════════════════════════════════

Após a Fase 2, produza o JSON final com os clusters enriquecidos.
A prioridade P1/P2/P3 é informativa — NUNCA a altere.

FORMATO DE RESPOSTA: JSON puro (sem markdown, sem ```):
{{
  "tldr_executivo": "Frase executiva de até 300 chars resumindo o dia para este perfil de investidor.",
  "clusters_selecionados": [
    {{
      "cluster_id": <int>,
      "titulo_whatsapp": "<emoji> Título curto (max 100 chars)",
      "bullet_impacto": "Frase de impacto COM dados factuais concretos (max 280 chars)",
      "fonte_principal": "Nome do jornal"
    }}
  ]
}}
"""

_TAMANHO_MAP = {
    "curto": {"min": 3, "max": 5, "label": "3-5"},
    "medio": {"min": 5, "max": 8, "label": "5-8"},
    "longo": {"min": 8, "max": 12, "label": "8-12"},
}


def _build_user_prompt(
    contexto: str,
    tags_interesse: List[str],
    tags_ignoradas: List[str],
    tipo_fonte: Optional[str],
    tamanho: str,
    instrucao_template: str = "",
) -> str:
    """Monta o prompt personalizado para um usuario a partir das suas preferencias visuais."""
    t = _TAMANHO_MAP.get(tamanho, _TAMANHO_MAP["medio"])
    return _PROMPT_USER_TEMPLATE.format(
        CONTEXTO_CLUSTERS_DIA=contexto,
        TAGS_FOCO=", ".join(tags_interesse) if tags_interesse else "Todas (sem filtro)",
        TAGS_IGNORADAS=", ".join(tags_ignoradas) if tags_ignoradas else "Nenhuma",
        TIPO_FONTE=tipo_fonte or "Todas",
        TAMANHO=t["label"],
        MIN_ITENS=t["min"],
        MAX_ITENS=t["max"],
        INSTRUCAO_TEMPLATE=instrucao_template or "Use o padrão de analista de Special Situations.",
    )


def gerar_resumo_para_usuario(
    user_id: int,
    target_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """
    Gera resumo personalizado para um usuario.

    Arquitetura de custo inteligente:
      - Contexto (_build_context_block): compartilhado, com cache por updated_at.
        Custo por dia: FIXO (uma leitura do banco, ~0 tokens LLM).
      - Prompt personalizado: UMA chamada LLM por usuario (não 3 personas).
        O prompt longo (~2K tokens) inclui preferencias + contexto.
        O LLM seleciona e formata — custo controlado.
      - Tool obter_textos_brutos: acionada pelo LLM APENAS quando precisa
        de dados factuais. Budget: 3 calls max por usuario.

    Para 100 usuarios: 100 chamadas LLM (vs. 300 do multi-persona).
    O contexto do banco é lido UMA VEZ e reutilizado em todas as 100 chamadas.
    """
    if target_date is None:
        target_date = get_date_brasil()

    print(f"\n[UserResumo] Gerando resumo para user_id={user_id}, data={target_date}")

    # 1. Contexto compartilhado (cache por updated_at)
    db_ctx = _open_db()
    try:
        from sqlalchemy import func as sqla_func
        max_updated = db_ctx.query(sqla_func.max(ClusterEvento.updated_at)).filter(
            sqla_func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == 'ativo',
        ).scalar()
        cache_key = f"{target_date.isoformat()}_{max_updated.isoformat() if max_updated else 'empty'}"

        cached = _CONTEXT_CACHE.get(cache_key)
        if cached:
            print(f"[UserResumo] Cache HIT ({cache_key})")
            contexto, avaliados_ids, fontes_map = cached
        else:
            contexto, avaliados_ids, fontes_map = _build_context_block(db_ctx, target_date)
            _CONTEXT_CACHE.clear()
            _CONTEXT_CACHE[cache_key] = (contexto, avaliados_ids, fontes_map)
    finally:
        db_ctx.close()

    if not avaliados_ids:
        return {"ok": False, "data": target_date.isoformat(), "error": "Nenhum cluster encontrado."}

    # 2. Preferencias do usuario
    db_prefs = _open_db()
    try:
        prefs = get_preferencias_usuario(db_prefs, user_id) if get_preferencias_usuario else None
        tags_interesse = (prefs.tags_interesse or []) if prefs else []
        tags_ignoradas = (prefs.tags_ignoradas or []) if prefs else []
        tipo_fonte = (prefs.tipo_fonte_preferido) if prefs else None
        tamanho = (prefs.tamanho_resumo or "medio") if prefs else "medio"
        template_id = (prefs.template_resumo_id) if prefs else None

        instrucao = ""
        if template_id and get_template_resumo:
            tpl = get_template_resumo(db_prefs, template_id)
            if tpl:
                instrucao = tpl.system_prompt or ""
    finally:
        db_prefs.close()

    # 3. UMA chamada LLM personalizada (não 3 personas)
    prompt_final = _build_user_prompt(
        contexto, tags_interesse, tags_ignoradas, tipo_fonte, tamanho, instrucao
    )
    print(f"[UserResumo] Prompt montado: {len(prompt_final)} chars, tags_foco={tags_interesse}, tamanho={tamanho}")

    db_llm = _open_db()
    try:
        raw_response = _run_llm_with_tools(
            db_llm, prompt_final,
            persona_name=f"user_{user_id}",
            tool_call_budget=_MAX_TOOL_CALLS_USER,
        )
    finally:
        db_llm.close()

    if not raw_response:
        return {"ok": False, "data": target_date.isoformat(), "error": "LLM não retornou resposta."}

    # 4. Validacao Pydantic
    try:
        contract = _validate_and_fix(raw_response, persona_name=f"user_{user_id}")
    except Exception as e:
        return {"ok": False, "data": target_date.isoformat(), "error": str(e)}

    escolhidos = [cs.cluster_id for cs in contract.clusters_selecionados]
    print(f"[UserResumo] Concluido: {len(escolhidos)} itens selecionados")

    return {
        "ok": True,
        "data": target_date.isoformat(),
        "contract_dict": contract.model_dump(),
        "clusters_avaliados_ids": avaliados_ids,
        "todos_clusters_escolhidos_ids": escolhidos,
        "fontes_map": fontes_map,
        "prompt_version": "USER_PERSONALIZED_V1",
    }


# --------------------------------------------------------------------------- #
# FORMATADOR WHATSAPP — Mensagem seccionada por persona
# --------------------------------------------------------------------------- #

def _format_fontes_label(fontes_list: List[str], max_fontes: int = 3) -> str:
    """Formata lista de fontes para exibição humana (sem IDs, com nomes reais)."""
    if not fontes_list:
        return ""
    # Remover duplicatas preservando ordem
    seen = set()
    unique = []
    for f in fontes_list:
        fl = f.strip()
        if fl and fl.lower() not in seen:
            seen.add(fl.lower())
            unique.append(fl)
    display = unique[:max_fontes]
    return ", ".join(display)


def formatar_whatsapp(
    resultado: Dict[str, Any],
    max_chars_por_msg: int = 4096,
) -> List[str]:
    """
    Formata o resultado unificado em string(s) para WhatsApp/terminal.
    Clusters são agrupados por `secao` (distressed, regulatorio, estrategico, geral).

    Returns:
        Lista de strings prontas para copiar-colar.
    """
    try:
        from backend.prompts import SECOES_RESUMO
    except ImportError:
        SECOES_RESUMO = {
            "distressed": {"emoji": "💀", "titulo": "DISTRESSED & NPLs"},
            "regulatorio": {"emoji": "⚖️", "titulo": "REGULATÓRIO & JURÍDICO"},
            "estrategico": {"emoji": "🏛️", "titulo": "M&A & MOVIMENTOS CORPORATIVOS"},
            "geral": {"emoji": "📋", "titulo": "DESTAQUES GERAIS"},
        }

    data_str = resultado.get("data", "")
    fontes_map = resultado.get("fontes_map", {})
    contract_dict = resultado.get("contract_dict", {})

    if not contract_dict:
        return [f"🚨 *RESUMO DO DIA* 🚨\n📅 {data_str}\n\n(Nenhum evento relevante identificado hoje.)\n\n_Gerado pelo AlphaFeed_"]

    tldr = contract_dict.get("tldr_executivo", "")
    clusters = contract_dict.get("clusters_selecionados", [])

    # Agrupar por secao
    por_secao: Dict[str, List[Dict]] = {}
    for cs in clusters:
        secao = cs.get("secao", "geral")
        por_secao.setdefault(secao, []).append(cs)

    header = f"🚨 *RESUMO DO DIA — SPECIAL SITUATIONS* 🚨\n"
    if data_str:
        header += f"📅 {data_str}\n"
    if tldr:
        header += f"\n_{tldr}_\n"
    header += "\n"

    sections: List[str] = []
    vistos: set = set()

    for secao_key in ["distressed", "regulatorio", "estrategico", "geral"]:
        items = por_secao.get(secao_key, [])
        if not items:
            continue

        config = SECOES_RESUMO.get(secao_key, {"emoji": "📋", "titulo": secao_key.upper()})
        section = f"{config['emoji']} *{config['titulo']}*\n\n"

        for cs in items:
            cid = cs.get("cluster_id")
            if cid is not None and cid in vistos:
                continue
            if cid is not None:
                vistos.add(cid)

            section += f"*{cs.get('titulo_whatsapp', '')}*\n"
            section += f"• {cs.get('bullet_impacto', '')}\n"

            real_fontes = fontes_map.get(cid, []) if cid else []
            fontes_str = _format_fontes_label(real_fontes)
            if not fontes_str:
                fontes_str = cs.get('fonte_principal', '')
            if fontes_str:
                section += f"_Fontes: {fontes_str}_\n"
            section += "\n"

        if "•" in section:
            sections.append(section.strip())

    if not sections:
        return [header + "(Nenhum evento relevante identificado hoje.)\n\n_Gerado pelo AlphaFeed_"]

    footer = "_Gerado pelo AlphaFeed_"
    full_msg = header + "\n\n".join(sections) + "\n\n" + footer

    if len(full_msg) <= max_chars_por_msg:
        return [full_msg]

    msgs: List[str] = []
    current = header
    for section in sections:
        if len(current) + len(section) + 10 > max_chars_por_msg:
            msgs.append(current.strip())
            current = "🚨 *RESUMO (cont.)* 🚨\n\n"
        current += section + "\n\n"
    current += footer
    msgs.append(current.strip())

    return msgs
