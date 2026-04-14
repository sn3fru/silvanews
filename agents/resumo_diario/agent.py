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
        get_resumo_default,
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
    get_resumo_default = None  # type: ignore
    get_date_brasil = None  # type: ignore
    PROMPT_CORRECAO_PYDANTIC_V1 = ""  # type: ignore

from agents.resumo_diario.tools.definitions import (
    ResumoDiarioContract,
    ResumoBarrettiContract,
    TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA,
    TOOL_BUSCAR_NA_WEB_SCHEMA,
    execute_obter_textos_brutos,
    execute_buscar_na_web,
)

_MAX_TOOL_CALLS = 5        # chamada unificada: permite aprofundamento seletivo
_MAX_TOOL_CALLS_USER = 8   # per-user: triagem + deep-dive em P1/P2 selecionados
_MAX_TOOL_CALLS_BARRETTI = 10  # barretti: min 7 noticias, cada uma pode precisar de aprofundamento
_MAX_ITERATIONS = 10      # acomoda tool-calling loop
# Teto de saida para todos os resumos (nao implica uso total; evita truncar JSON grande)
_MAX_OUTPUT_TOKENS_RESUMO = 16384

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

def _load_yesterday_context(db, target_date: datetime.date) -> str:
    """
    Carrega os clusters selecionados no resumo default do dia anterior.
    Retorna um bloco de texto para injeção no prompt, ou string vazia se não houver.
    """
    if get_resumo_default is None:
        return ""
    try:
        yesterday = target_date - datetime.timedelta(days=1)
        resumo_ontem = get_resumo_default(db, yesterday)
        if not resumo_ontem:
            return ""

        escolhidos = resumo_ontem.clusters_escolhidos_ids or []
        if not escolhidos:
            return ""

        texto = resumo_ontem.texto_gerado or ""
        titulos_ontem: List[str] = []

        # metadados IS the contract_dict (saved directly by create_resumo_usuario)
        contract = resumo_ontem.metadados or {}
        if not contract.get("clusters_selecionados") and texto:
            try:
                contract = json.loads(texto) if texto.strip().startswith("{") else {}
            except Exception:
                contract = {}

        for cs in contract.get("clusters_selecionados", []):
            titulo = cs.get("titulo_whatsapp", "")
            if titulo:
                titulos_ontem.append(titulo)

        if not titulos_ontem:
            return ""

        linhas = [f"  - {t}" for t in titulos_ontem]
        bloco = (
            f"\n--- CONTEXTO DE ONTEM ({yesterday.strftime('%d/%m')}) ---\n"
            f"Estes temas JÁ FORAM cobertos no resumo de ontem:\n"
            + "\n".join(linhas)
            + "\n\nSe algum destes temas REAPARECER hoje SEM fato novo concreto, NÃO o inclua.\n"
            f"Se houver desdobramento novo, foque exclusivamente no QUE MUDOU.\n"
            f"--- FIM CONTEXTO DE ONTEM ---\n"
        )
        print(f"[ResumoDiario] Contexto de ontem carregado: {len(titulos_ontem)} títulos")
        return bloco
    except Exception as e:
        print(f"[ResumoDiario] Falha ao carregar contexto de ontem: {e}")
        return ""


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


def _resolve_fontes_from_artigos(db, cluster_id: int) -> List[str]:
    """
    Fallback robusto: busca nomes de fontes diretamente dos artigos do cluster.
    Tenta: artigo.jornal → metadados.fonte_original → metadados.arquivo_origem.
    Normaliza cada nome via normalizar_fonte_display().
    """
    try:
        from backend.database import ArtigoBruto
        from backend.utils import normalizar_fonte_display
    except ImportError:
        return []

    try:
        artigos = db.query(
            ArtigoBruto.jornal, ArtigoBruto.metadados
        ).filter(ArtigoBruto.cluster_id == cluster_id).all()
    except Exception:
        return []

    nomes: List[str] = []
    for jornal, metadados in artigos:
        raw_name = ""
        if jornal:
            raw_name = jornal.strip()
        if not raw_name or raw_name.lower() in ("fonte desconhecida", "n/a", ""):
            meta = metadados or {}
            raw_name = (
                meta.get("fonte_original")
                or meta.get("jornal")
                or ""
            ).strip()
        if not raw_name or raw_name.lower() in ("fonte desconhecida", "n/a", ""):
            meta = metadados or {}
            arq = meta.get("arquivo_origem", "")
            if arq:
                raw_name = arq.replace(".pdf", "").replace(".json", "").strip()

        clean = normalizar_fonte_display(raw_name)
        if clean:
            nomes.append(clean)

    seen = set()
    unique = []
    for n in nomes:
        if n.lower() not in seen:
            seen.add(n.lower())
            unique.append(n)
    return unique


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

        # Fallback: se nenhuma fonte foi resolvida via CRUD, busca direto dos artigos
        if not nomes_fontes_unique:
            nomes_fontes_unique = _resolve_fontes_from_artigos(db, cid)

        fontes_map[cid] = nomes_fontes_unique
        fontes_label = ", ".join(nomes_fontes_unique[:3]) if nomes_fontes_unique else ""

        if prio in ("P1_CRITICO", "P2_ESTRATEGICO"):
            resumo = resumo_raw
        else:
            resumo = _truncate_resumo_p3(resumo_raw)

        tipo_fonte = tipo_fonte_map.get(cid, "")

        fontes_ctx = f"(Fontes: {fontes_label})" if fontes_label else "(Use obter_textos_brutos_cluster para identificar a fonte)"
        linhas.append(
            f"[ID={cid}] [{prio}] [{tag}] [{tipo_fonte}] "
            f"{fontes_ctx}\n"
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
        f"\nVOLUME MÍNIMO OBRIGATÓRIO:\n"
        f"- QUENTE: 10-15 itens distribuidos pelas secoes.\n"
        f"- MORNO: 7-12 itens. MINIMO ABSOLUTO: 5 itens.\n"
        f"- FRIO: 5-8 itens (baixe a regua, selecione os mais relevantes que existirem).\n"
        f"- NUNCA retorne menos de 5 itens quando ha 10+ clusters disponiveis.\n"
        f"- Inclua noticias de TODAS AS FONTES (fisico, online, internacional).\n"
        f"--- FIM CONTEXTO ---\n\n"
    )

    yesterday_ctx = _load_yesterday_context(db, target_date)

    contexto = header_temperatura + yesterday_ctx + "\n".join(linhas)
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
    max_output_tokens: int = _MAX_OUTPUT_TOKENS_RESUMO,
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
        generation_config={"temperature": 0.2, "max_output_tokens": max_output_tokens},
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
            generation_config={"temperature": 0.2, "max_output_tokens": max_output_tokens},
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

    _SECOES_VALIDAS_PYDANTIC = {"foco_analista", "distressed", "estrategico", "regulatorio", "internacional"}
    for cs in data.get("clusters_selecionados", []):
        if isinstance(cs, dict) and cs.get("secao") not in _SECOES_VALIDAS_PYDANTIC:
            cs["secao"] = "distressed"

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

    SECAO_EMOJIS = {"foco_analista": "🎯", "distressed": "💀", "estrategico": "🏛️", "regulatorio": "⚖️", "internacional": "🌍"}
    print(f"\n{'='*60}")
    print(f"[ResumoDiario] RESULTADO — {len(escolhidos)} itens de {len(avaliados_ids)} clusters")
    print(f"{'='*60}")
    if contract.tldr_executivo:
        print(f"  TL;DR: {contract.tldr_executivo}")
    for secao_key in ["foco_analista", "distressed", "estrategico", "regulatorio", "internacional"]:
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
# MODO PER-USER (v4.0): Chassis imutável + slots personalizáveis
# --------------------------------------------------------------------------- #
# Arquitetura de 2 camadas:
#   CHASSIS (imutável): PROMPT_MASTER_V2 em backend/prompts.py
#     → Rejeição de ruído, tools, formato JSON, seções obrigatórias
#   SLOTS (personalizáveis): Tags, empresas, teses, tamanho, instrução livre
#     → Injetados nos "buracos" do chassis via _build_user_prompt()
#
# O chassis NUNCA é sobrescrito pelas preferências do usuário.
# As preferências são filtros SEGUROS dentro de um prompt blindado.
# --------------------------------------------------------------------------- #

_TAMANHO_MAP = {
    "curto": {"min": 3, "max": 5, "label": "3-5"},
    "medio": {"min": 5, "max": 8, "label": "5-8"},
    "longo": {"min": 8, "max": 12, "label": "8-12"},
}

# Defaults para usuários que não configuraram preferências
_DEFAULTS_PREFERENCIAS = {
    "tags_foco": "Geral — Special Situations (distressed, M&A, regulatório)",
    "tags_ignoradas": "Nenhuma",
    "empresas_radar": "Sem filtro específico — priorizar os eventos mais críticos do dia",
    "teses_juridicas": "Sem filtro específico — cobrir decisões relevantes do STF/STJ/CADE",
    "instrucao_livre": "Priorize os eventos mais críticos do dia para a mesa de Special Situations.",
}


def _build_user_prompt(
    contexto: str,
    tags_interesse: List[str],
    tags_ignoradas: List[str],
    tipo_fonte: Optional[str],
    tamanho: str,
    instrucao_template: str = "",
    empresas_radar: str = "",
    teses_juridicas: str = "",
) -> str:
    """
    Monta o prompt personalizado usando o chassis PROMPT_MASTER_V2.

    Injeções seguras (os únicos pontos de personalização):
      TAGS_FOCO, TAGS_IGNORADAS, EMPRESAS_RADAR, TESES_JURIDICAS,
      INSTRUCAO_LIVRE_USUARIO, MIN_ITENS, MAX_ITENS, CONTEXTO_CLUSTERS_DIA
    """
    try:
        from backend.prompts import PROMPT_MASTER_V2
    except ImportError:
        raise RuntimeError("PROMPT_MASTER_V2 não encontrado em backend/prompts.py")

    t = _TAMANHO_MAP.get(tamanho, _TAMANHO_MAP["medio"])

    has_empresas = bool(empresas_radar and empresas_radar.strip())
    has_teses = bool(teses_juridicas and teses_juridicas.strip())
    has_tags_custom = bool(tags_interesse)
    has_foco = has_empresas or has_teses or has_tags_custom

    tags_foco_str = ", ".join(tags_interesse) if tags_interesse else _DEFAULTS_PREFERENCIAS["tags_foco"]
    tags_ign_str = ", ".join(tags_ignoradas) if tags_ignoradas else _DEFAULTS_PREFERENCIAS["tags_ignoradas"]
    empresas_str = empresas_radar.strip() if has_empresas else _DEFAULTS_PREFERENCIAS["empresas_radar"]
    teses_str = teses_juridicas.strip() if has_teses else _DEFAULTS_PREFERENCIAS["teses_juridicas"]
    instrucao_str = instrucao_template.strip() if instrucao_template and instrucao_template.strip() else _DEFAULTS_PREFERENCIAS["instrucao_livre"]

    prompt = PROMPT_MASTER_V2.format(
        TAGS_FOCO=tags_foco_str,
        TAGS_IGNORADAS=tags_ign_str,
        EMPRESAS_RADAR=empresas_str,
        TESES_JURIDICAS=teses_str,
        INSTRUCAO_LIVRE_USUARIO=instrucao_str,
        MIN_ITENS=t["min"],
        MAX_ITENS=t["max"],
        MAX_TOOL_CALLS=_MAX_TOOL_CALLS_USER,
        CONTEXTO_CLUSTERS_DIA=contexto,
    )

    if not has_foco:
        prompt = prompt.replace(
            '1. 🎯 FOCO DO ANALISTA (secao="foco_analista"): Eventos que respondam diretamente às "Empresas no Radar", "Teses Jurídicas" ou "Tags de Foco" do analista. Esta é a seção de MAIOR VALOR — se o analista indicou preferências, preencha-a primeiro.\n\n',
            '',
        )
        prompt = prompt.replace(
            'PASSO 1 — TRIAGEM: Leia TODOS os clusters. Marque os que atendem às diretrizes do analista (seção "Foco"). Depois, marque os que atendem aos critérios de cada seção temática.',
            'PASSO 1 — TRIAGEM: Leia TODOS os clusters. Marque os que atendem aos critérios de cada seção temática.',
        )

    return prompt


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

    # 2. Preferencias do usuario (extraidas do banco)
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

        config_extra = (prefs.config_extra or {}) if prefs else {}
        instrucoes_user = config_extra.get("instrucoes_resumo", "")
        if instrucoes_user:
            instrucao = instrucoes_user

        empresas_radar = config_extra.get("empresas_radar", "")
        teses_juridicas = config_extra.get("teses_juridicas", "")
    finally:
        db_prefs.close()

    # 3. UMA chamada LLM — chassis PROMPT_MASTER_V2 + slots personalizáveis
    prompt_final = _build_user_prompt(
        contexto, tags_interesse, tags_ignoradas, tipo_fonte, tamanho,
        instrucao, empresas_radar, teses_juridicas,
    )
    print(f"[UserResumo] Prompt montado: {len(prompt_final)} chars, tags_foco={tags_interesse}, tamanho={tamanho}, empresas={empresas_radar or 'default'}")

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
        "prompt_version": "MASTER_V2_PERSONALIZED",
    }


# --------------------------------------------------------------------------- #
# PERFIL BARRETTI — Capital Solutions / Special Situations (prompt dedicado)
# --------------------------------------------------------------------------- #

def _validate_and_fix_barretti(raw_json_str: str) -> ResumoBarrettiContract:
    """Valida JSON do LLM com ResumoBarrettiContract. Fallback via LLM se falhar."""
    from pydantic import ValidationError

    tag = "[Barretti]"
    data = _extract_json_from_text(raw_json_str)
    if data is None:
        raise ValueError(f"{tag} Impossível extrair JSON: {raw_json_str[:500]}")

    _PRIORIDADES_VALIDAS = {"Alta", "Media", "Baixa"}
    _ACIONABILIDADE_VALIDA = {"Acao imediata", "Monitorar de perto", "Apenas contextual"}
    for n in data.get("noticias", []):
        if isinstance(n, dict):
            if n.get("secao") is None:
                n["secao"] = ""
            if n.get("prioridade") not in _PRIORIDADES_VALIDAS:
                n["prioridade"] = "Media"
            if n.get("acionabilidade") not in _ACIONABILIDADE_VALIDA:
                n["acionabilidade"] = "Monitorar de perto"
            if not n.get("follow_ups"):
                n["follow_ups"] = ["Acompanhar desdobramentos", "Verificar impacto no setor"]
            if not n.get("tags"):
                n["tags"] = ["Geral"]
            for str_field in ("titulo", "jornal", "resumo_executivo", "impacto_ss",
                              "acionabilidade_justificativa", "fonte_principal"):
                if n.get(str_field) is None:
                    n[str_field] = ""

    _BLOCOS_MINIMOS = {
        "radar_oportunidades": 2,
        "radar_riscos": 2,
        "watchlist": 2,
        "action_items": 2,
        "perguntas_estrategicas": 3,
    }
    for bloco, minimo in _BLOCOS_MINIMOS.items():
        items = data.get(bloco)
        if not items or not isinstance(items, list):
            data[bloco] = [f"(Pendente de análise — {bloco.replace('_', ' ')})"] * minimo
        elif len(items) < minimo:
            while len(items) < minimo:
                items.append(f"(Item complementar — {bloco.replace('_', ' ')})")

    temas = data.get("top_5_temas")
    if isinstance(temas, list):
        data["top_5_temas"] = [t[:80] if isinstance(t, str) else str(t) for t in temas[:5]]

    try:
        return ResumoBarrettiContract(**data)
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
            generation_config={"temperature": 0.1, "max_output_tokens": _MAX_OUTPUT_TOKENS_RESUMO},
        )
        fixed_text = (resp.text or "").strip()
        print(f"{tag} Fallback Pydantic recebido ({len(fixed_text)} chars)")

        fixed_data = _extract_json_from_text(fixed_text)
        if fixed_data is None:
            raise ValueError(f"{tag} Fallback falhou: {fixed_text[:500]}")

        return ResumoBarrettiContract(**fixed_data)


def gerar_resumo_barretti(
    target_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """
    Gera resumo no formato completo Capital Solutions / Special Situations.

    Usa PROMPT_BARRETTI_V1 (texto do Gabriel) com contrato Pydantic dedicado
    (ResumoBarrettiContract). Reaproveita o contexto compartilhado.
    """
    if target_date is None:
        target_date = get_date_brasil()

    try:
        from backend.prompts import PROMPT_BARRETTI_V1
    except ImportError:
        return {"ok": False, "data": target_date.isoformat(), "error": "PROMPT_BARRETTI_V1 não encontrado."}

    print(f"\n[Barretti] {target_date.isoformat()} — Construindo contexto...")

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
            print(f"[Barretti] Cache HIT ({cache_key})")
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
        return {"ok": False, "data": target_date.isoformat(), "error": "Nenhum cluster encontrado."}

    print(f"[Barretti] {len(avaliados_ids)} clusters, {len(contexto)} chars de contexto")

    prompt_final = PROMPT_BARRETTI_V1.format(
        CONTEXTO_CLUSTERS_DIA=contexto,
        MAX_TOOL_CALLS=_MAX_TOOL_CALLS_BARRETTI,
    )

    db_llm = _open_db()
    try:
        raw_response = _run_llm_with_tools(
            db_llm, prompt_final,
            persona_name="barretti",
            tool_call_budget=_MAX_TOOL_CALLS_BARRETTI,
            max_output_tokens=_MAX_OUTPUT_TOKENS_RESUMO,
        )
    finally:
        try:
            db_llm.close()
        except Exception:
            pass

    if not raw_response:
        return {"ok": False, "data": target_date.isoformat(), "error": "LLM não retornou resposta."}

    try:
        contract = _validate_and_fix_barretti(raw_response)
    except Exception as e:
        return {"ok": False, "data": target_date.isoformat(), "error": f"Validação Pydantic falhou: {e}"}

    escolhidos = [n.cluster_id for n in contract.noticias]

    print(f"\n{'='*60}")
    print(f"[Barretti] RESULTADO — {len(contract.noticias)} noticias de {len(avaliados_ids)} clusters")
    print(f"{'='*60}")
    print(f"  Top 5: {', '.join(contract.top_5_temas[:5])}")
    for i, n in enumerate(contract.noticias, 1):
        print(f"  {i}. [{n.prioridade}] {n.titulo[:80]}")
    print(f"{'='*60}")

    return {
        "ok": True,
        "data": target_date.isoformat(),
        "contract_dict": contract.model_dump(),
        "clusters_avaliados_ids": avaliados_ids,
        "todos_clusters_escolhidos_ids": sorted(set(escolhidos)),
        "fontes_map": fontes_map,
        "prompt_version": "BARRETTI_V1",
    }


def formatar_barretti(resultado: Dict[str, Any]) -> str:
    """
    Formata o resultado do ResumoBarrettiContract em texto rico para terminal/WhatsApp.
    """
    data_str = resultado.get("data", "")
    contract_dict = resultado.get("contract_dict", {})

    if not contract_dict:
        return f"Resumo Barretti — {data_str}\n\n(Nenhum evento relevante identificado hoje.)"

    date_label = data_str
    if data_str and "-" in data_str:
        parts = data_str.split("-")
        if len(parts) == 3:
            date_label = f"{parts[2]}/{parts[1]}/{parts[0]}"

    lines: List[str] = []
    sep = "=" * 60
    sep2 = "-" * 60

    lines.append(sep)
    lines.append("BRIEFING EXECUTIVO — CAPITAL SOLUTIONS / SPECIAL SITUATIONS")
    lines.append(f"Data: {date_label}")
    lines.append(sep)

    top5 = contract_dict.get("top_5_temas", [])
    if top5:
        lines.append("")
        lines.append("TOP 5 TEMAS DO DIA:")
        for i, tema in enumerate(top5, 1):
            lines.append(f"  {i}. {tema}")

    noticias = contract_dict.get("noticias", [])
    for i, n in enumerate(noticias, 1):
        lines.append("")
        lines.append(sep2)
        prioridade = n.get("prioridade", "Media")
        titulo = n.get("titulo", "")
        jornal = n.get("jornal", "")
        secao = n.get("secao", "")
        secao_str = f" / {secao}" if secao else ""

        lines.append(f"{i}. {titulo} / {jornal}{secao_str}")
        lines.append(f"Prioridade: {prioridade}")

        tags = n.get("tags", [])
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")

        lines.append(n.get("resumo_executivo", ""))

        impacto = n.get("impacto_ss", "")
        if impacto:
            lines.append(f"→ {impacto}")

        acion = n.get("acionabilidade", "Monitorar de perto")
        acion_just = n.get("acionabilidade_justificativa", "")
        lines.append(f"[{acion}] {acion_just}")

        follow_ups = n.get("follow_ups", [])
        if follow_ups:
            lines.append("  " + " | ".join(follow_ups))

    def _format_block(title: str, items: List, prefix: str = "•"):
        if not items:
            return
        lines.append("")
        lines.append(sep)
        lines.append(title)
        lines.append(sep)
        for item in items:
            lines.append(f"  {prefix} {item}")

    _format_block("RADAR DE OPORTUNIDADES", contract_dict.get("radar_oportunidades", []))
    _format_block("RADAR DE RISCOS", contract_dict.get("radar_riscos", []))
    _format_block("WATCHLIST EXECUTIVA", contract_dict.get("watchlist", []))
    _format_block("ACTION ITEMS SUGERIDOS", contract_dict.get("action_items", []))
    _format_block("PERGUNTAS ESTRATÉGICAS ABERTAS", contract_dict.get("perguntas_estrategicas", []))

    lines.append("")
    lines.append(sep)
    lines.append("Gerado pelo AlphaFeed — Perfil Capital Solutions / Special Situations")
    lines.append(sep)

    return "\n".join(lines)


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
            "foco_analista": {"emoji": "🎯", "titulo": "FOCO DO ANALISTA"},
            "distressed": {"emoji": "💀", "titulo": "DISTRESSED & NPLs"},
            "estrategico": {"emoji": "🏛️", "titulo": "M&A & MOVIMENTOS CORPORATIVOS"},
            "regulatorio": {"emoji": "⚖️", "titulo": "REGULATÓRIO & JURÍDICO"},
            "internacional": {"emoji": "🌍", "titulo": "RADAR GLOBAL / INTERNACIONAL"},
        }

    data_str = resultado.get("data", "")
    fontes_map = resultado.get("fontes_map", {})
    contract_dict = resultado.get("contract_dict", {})

    if not contract_dict:
        return [f"*Resumo do dia {data_str}*\n\n(Nenhum evento relevante identificado hoje.)"]

    tldr = contract_dict.get("tldr_executivo", "")
    clusters = contract_dict.get("clusters_selecionados", [])

    _SECOES_VALIDAS = {"foco_analista", "distressed", "estrategico", "regulatorio", "internacional"}
    por_secao: Dict[str, List[Dict]] = {}
    for cs in clusters:
        secao = cs.get("secao", "distressed")
        if secao not in _SECOES_VALIDAS:
            secao = "distressed"
        por_secao.setdefault(secao, []).append(cs)

    date_label = data_str
    if data_str and "-" in data_str:
        parts = data_str.split("-")
        if len(parts) == 3:
            date_label = f"{parts[2]}/{parts[1]}"

    header = f"*Resumo do dia {date_label} — Special Situations*\n"
    if tldr:
        header += f"\n_{tldr}_\n"
    header += "\n"

    sections: List[str] = []
    vistos: set = set()

    for secao_key in ["foco_analista", "distressed", "estrategico", "regulatorio", "internacional"]:
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
                fp = cs.get('fonte_principal', '') or ''
                fp_lower = fp.lower()
                _FONTES_INVALIDAS = (
                    '', 'fonte não identificada', 'fonte desconhecida',
                    'não identificada', 'n/a', 'desconhecida',
                    'sem fonte', 'unknown',
                )
                is_invalid = (
                    fp_lower in _FONTES_INVALIDAS
                    or 'obter_textos_brutos' in fp_lower
                    or 'não identificada' in fp_lower
                    or 'usar obter' in fp_lower
                    or 'identificar a fonte' in fp_lower
                )
                if not is_invalid and fp.strip():
                    fontes_str = fp.strip()
            if fontes_str:
                section += f"_Fontes: {fontes_str}_\n"
            section += "\n"

        if "•" in section:
            sections.append(section.strip())

    if not sections:
        return [header + "(Nenhum evento relevante identificado hoje.)"]

    full_msg = header + "\n\n".join(sections)

    if len(full_msg) <= max_chars_por_msg:
        return [full_msg.strip()]

    msgs: List[str] = []
    current = header
    for section in sections:
        if len(current) + len(section) + 10 > max_chars_por_msg:
            msgs.append(current.strip())
            current = "*Resumo (cont.)*\n\n"
        current += section + "\n\n"
    msgs.append(current.strip())

    return msgs
