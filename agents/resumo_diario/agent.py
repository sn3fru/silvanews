"""
Agente de Resumo Diário — Curadoria Multi-Persona / Per-User para WhatsApp

Arquitetura v3.0 (Multi-Tenant):
  1. PRÉ-QUERY (Map-Reduce): _build_context_block() recolhe TODOS os clusters do dia UMA VEZ.
     Esse contexto é COMPARTILHADO entre todos os usuarios — nunca duplicado.
  2. MODO MULTI-PERSONA (legado): Roda 3 personas fixas em paralelo (distressed, regulatorio, estrategista).
  3. MODO PER-USER (v3): Recebe preferencias do usuario e gera UMA chamada LLM personalizada.
     O prompt longo inclui as preferencias visuais (tags, tamanho, foco) mas o CONTEXTO é o mesmo.
     Custo: 1 chamada LLM por usuario (vs. 3 do modo multi-persona).
  4. VALIDAÇÃO: JSON → Pydantic → fallback.
  5. FORMATAÇÃO: WhatsApp ou texto puro.

READ-ONLY — não altera banco, não faz split/merge. Prioridade P1/P2/P3 é GLOBAL, nunca mutada.
"""

from __future__ import annotations

import json
import os
import re
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        PERSONAS_RESUMO_DIARIO,
    )
except Exception:
    SessionLocal = None  # type: ignore
    ClusterEvento = None  # type: ignore
    get_clusters_for_feed_by_date = None  # type: ignore
    get_preferencias_usuario = None  # type: ignore
    get_template_resumo = None  # type: ignore
    get_date_brasil = None  # type: ignore
    PROMPT_CORRECAO_PYDANTIC_V1 = ""  # type: ignore
    PERSONAS_RESUMO_DIARIO = {}  # type: ignore

from agents.resumo_diario.tools.definitions import (
    ResumoDiarioContract,
    TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA,
    TOOL_BUSCAR_NA_WEB_SCHEMA,
    execute_obter_textos_brutos,
    execute_buscar_na_web,
)

# Controle de iterações (por persona / por usuario)
_MAX_TOOL_CALLS = 3       # multi-persona legacy (3 personas x 3 = 9 total)
_MAX_TOOL_CALLS_USER = 8  # per-user: triagem + deep-dive em P1/P2 selecionados
_MAX_ITERATIONS = 10      # aumentado para acomodar Fase 2 (deep-dive)

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

        # Extrair nomes de fontes reais (jornais) do campo "fontes"
        # CRUD retorna fontes como lista de dicts: {nome, tipo, url, autor, pagina}
        raw_fontes = c.get("fontes", [])
        nomes_fontes = []
        if isinstance(raw_fontes, list):
            for f in raw_fontes:
                if isinstance(f, dict):
                    nome = (f.get("nome") or "").strip()
                    if nome and nome.lower() != "fonte desconhecida":
                        nomes_fontes.append(nome)
                elif isinstance(f, str) and f.strip():
                    nomes_fontes.append(f.strip())
        # Dedup preservando ordem
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

    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        tools=[tool_declaration],
    )

    tag = f"[{persona_name}]" if persona_name else "[ResumoDiario]"
    print(f"{tag} Iniciando chamada ao LLM...")
    response = model.generate_content(
        prompt_text,
        generation_config={"temperature": 0.2, "max_output_tokens": 4096},
    )

    tool_calls_used = 0
    iterations = 0

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
            print(f"{tag} LLM respondeu ({len(final_text)} chars, {tool_calls_used} tool calls)")
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
                    print(f"{tag} Budget de tool calls esgotado ({tool_call_budget}).")
                    result_data = {"error": "Limite de chamadas a ferramentas atingido. Produza o JSON final agora."}
                else:
                    print(f"{tag} Tool call #{tool_calls_used}: obter_textos_brutos_cluster(cluster_id={cluster_id})")
                    result_data = execute_obter_textos_brutos(db, cluster_id)

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
                    print(f"{tag} Tool call #{tool_calls_used}: buscar_na_web(query='{query[:60]}')")
                    result_data = execute_buscar_na_web(query)

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

        response = model.generate_content(
            [
                genai.protos.Content(role="user", parts=[genai.protos.Part(text=prompt_text)]),
                candidate.content,
                genai.protos.Content(role="function", parts=function_responses),
            ],
            generation_config={"temperature": 0.2, "max_output_tokens": 4096},
        )

    print(f"{tag} Limite de iterações atingido ({_MAX_ITERATIONS}).")
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
# ETAPA 4: EXECUÇÃO DE UMA PERSONA (unidade atômica)
# --------------------------------------------------------------------------- #

def _run_persona(
    persona_key: str,
    persona_config: Dict[str, Any],
    contexto: str,
    db_factory,
) -> Dict[str, Any]:
    """
    Executa uma persona completa: prompt → LLM → validação Pydantic.
    Cada thread recebe sua própria sessão de banco (thread-safe).

    Returns:
        Dict com: persona_key, ok, contract (ResumoDiarioContract ou None), error
    """
    tag = f"[{persona_key}]"
    print(f"{tag} Iniciando persona: {persona_config.get('descricao', '')}")

    db = db_factory()
    try:
        prompt_template = persona_config["prompt"]
        prompt_final = prompt_template.format(CONTEXTO_CLUSTERS_DIA=contexto)

        raw_response = _run_llm_with_tools(db, prompt_final, persona_name=persona_key)
        if not raw_response:
            return {"persona_key": persona_key, "ok": False, "contract": None, "error": "LLM não retornou resposta."}

        contract = _validate_and_fix(raw_response, persona_name=persona_key)

        escolhidos = [cs.cluster_id for cs in contract.clusters_selecionados]
        print(f"{tag} Concluído: {len(contract.clusters_selecionados)} itens selecionados (IDs: {escolhidos})")

        return {"persona_key": persona_key, "ok": True, "contract": contract, "error": None}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"persona_key": persona_key, "ok": False, "contract": None, "error": str(e)}
    finally:
        try:
            db.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# FUNÇÃO PRINCIPAL — Orquestração Multi-Persona Paralela
# --------------------------------------------------------------------------- #

def gerar_resumo_diario(
    target_date: Optional[datetime.date] = None,
    personas: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ponto de entrada do agente de resumo diário (Multi-Persona).

    Fluxo:
      1. Constrói contexto UMA VEZ (_build_context_block)
      2. Dispara N personas em PARALELO (ThreadPoolExecutor)
      3. Agrega resultados de todas as personas

    Args:
        target_date: Data para gerar o resumo (padrão: hoje).
        personas: Dict de personas a usar (padrão: PERSONAS_RESUMO_DIARIO).

    Returns:
        Dict com:
            - "ok": bool (True se pelo menos 1 persona retornou)
            - "data": str (ISO date)
            - "personas_resultados": dict[str, {ok, contract_dict, error}]
            - "clusters_avaliados_ids": list[int]
            - "todos_clusters_escolhidos_ids": list[int] (união de todas as personas)
            - "prompt_version": str
    """
    if target_date is None:
        target_date = get_date_brasil()

    if personas is None:
        personas = PERSONAS_RESUMO_DIARIO

    print(f"\n{'='*60}")
    print(f"[ResumoDiario] MULTI-PERSONA — {target_date.isoformat()}")
    print(f"[ResumoDiario] Personas ativas: {list(personas.keys())}")
    print(f"{'='*60}")

    # 1. Map-Reduce: montar contexto (com cache por updated_at)
    db_ctx = _open_db()
    fontes_map: Dict[int, List[str]] = {}
    try:
        # Chave de cache: data + max(updated_at) de clusters do dia
        from sqlalchemy import func as sqla_func
        max_updated = db_ctx.query(sqla_func.max(ClusterEvento.updated_at)).filter(
            sqla_func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == 'ativo',
        ).scalar()
        cache_key = f"{target_date.isoformat()}_{max_updated.isoformat() if max_updated else 'empty'}"

        cached = _CONTEXT_CACHE.get(cache_key)
        if cached:
            print(f"[ResumoDiario] Cache HIT para contexto ({cache_key})")
            contexto, avaliados_ids, fontes_map = cached
        else:
            contexto, avaliados_ids, fontes_map = _build_context_block(db_ctx, target_date)
            _CONTEXT_CACHE.clear()  # limpa cache antigo
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

    # 2. Disparar personas em paralelo
    personas_resultados: Dict[str, Any] = {}
    todos_escolhidos: List[int] = []

    def db_factory():
        return _open_db()

    with ThreadPoolExecutor(max_workers=len(personas)) as executor:
        futures = {}
        for p_key, p_config in personas.items():
            future = executor.submit(_run_persona, p_key, p_config, contexto, db_factory)
            futures[future] = p_key

        for future in as_completed(futures):
            p_key = futures[future]
            try:
                result = future.result()
                personas_resultados[p_key] = {
                    "ok": result["ok"],
                    "contract_dict": result["contract"].model_dump() if result["contract"] else None,
                    "error": result["error"],
                }
                if result["ok"] and result["contract"]:
                    ids = [cs.cluster_id for cs in result["contract"].clusters_selecionados]
                    todos_escolhidos.extend(ids)
            except Exception as e:
                personas_resultados[p_key] = {
                    "ok": False,
                    "contract_dict": None,
                    "error": str(e),
                }

    # 3. Resultado agregado
    algum_sucesso = any(r["ok"] for r in personas_resultados.values())

    resultado = {
        "ok": algum_sucesso,
        "data": target_date.isoformat(),
        "personas_resultados": personas_resultados,
        "clusters_avaliados_ids": avaliados_ids,
        "todos_clusters_escolhidos_ids": sorted(set(todos_escolhidos)),
        "fontes_map": fontes_map,  # cluster_id -> ["Folha", "Valor", ...]
        "prompt_version": "MULTI-PERSONA_V1",
    }

    print(f"\n{'='*60}")
    print(f"[ResumoDiario] RESULTADO CONSOLIDADO")
    print(f"[ResumoDiario]   Clusters avaliados: {len(avaliados_ids)}")
    print(f"[ResumoDiario]   Total escolhidos (todas personas): {len(set(todos_escolhidos))}")
    for p_key, p_res in personas_resultados.items():
        emoji = personas.get(p_key, {}).get("emoji", "")
        if p_res["ok"]:
            n = len(p_res["contract_dict"]["clusters_selecionados"]) if p_res["contract_dict"] else 0
            print(f"[ResumoDiario]   {emoji} {p_key}: {n} itens ✅")
        else:
            print(f"[ResumoDiario]   {emoji} {p_key}: FALHOU — {p_res['error']}")
    print(f"{'='*60}")

    return resultado


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
        "personas_resultados": {
            f"user_{user_id}": {
                "ok": True,
                "contract_dict": contract.model_dump(),
                "error": None,
            }
        },
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
    personas_config: Optional[Dict[str, Any]] = None,
    max_chars_por_msg: int = 4096,
) -> List[str]:
    """
    Formata o resultado multi-persona em string(s) para WhatsApp.
    Cada persona vira uma seção: 💀 DISTRESS, ⚖️ REGULATÓRIO, 🏛️ M&A.

    REGRAS DE FORMATAÇÃO WHATSAPP:
    - *negrito* para títulos de seção
    - _itálico_ para fontes e rodapé
    - Sem cluster_ids visíveis (são jargão de DB)
    - Apenas nomes reais dos jornais (ex.: Fontes: Valor, Folha, Estadão) — sem links

    Returns:
        Lista de strings prontas para copiar-colar no WhatsApp.
    """
    if personas_config is None:
        personas_config = PERSONAS_RESUMO_DIARIO

    data_str = resultado.get("data", "")
    personas_resultados = resultado.get("personas_resultados", {})
    fontes_map = resultado.get("fontes_map", {})  # cluster_id -> ["Folha", "Valor", ...]

    header = f"🚨 *RESUMO DO DIA — SPECIAL SITUATIONS* 🚨\n"
    if data_str:
        header += f"📅 {data_str}\n"
    header += "\n"

    sections: List[str] = []
    vistos: set = set()

    for p_key in ["distressed", "regulatorio", "estrategista"]:
        p_res = personas_resultados.get(p_key)
        if not p_res or not p_res.get("ok") or not p_res.get("contract_dict"):
            continue

        config = personas_config.get(p_key, {})
        emoji = config.get("emoji", "📋")
        titulo = config.get("titulo_secao", p_key.upper())
        contract_dict = p_res["contract_dict"]
        clusters = contract_dict.get("clusters_selecionados", [])

        if not clusters:
            continue

        section = f"{emoji} *{titulo}*\n\n"

        for cs in clusters:
            cid = cs.get("cluster_id")
            if cid is not None and cid in vistos:
                continue
            if cid is not None:
                vistos.add(cid)

            # Título (sem cluster_id — é jargão técnico)
            section += f"*{cs['titulo_whatsapp']}*\n"

            # Bullet de impacto
            section += f"• {cs['bullet_impacto']}\n"

            # Fontes reais do DB (fallback: o que o LLM escreveu)
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
        return [header + "(Nenhum evento relevante identificado hoje.)\n\n_🕐 Gerado pelo AlphaFeed_"]

    footer = "_🕐 Gerado pelo AlphaFeed_"
    full_msg = header + "\n\n".join(sections) + "\n\n" + footer

    # Split se necessário
    if len(full_msg) <= max_chars_por_msg:
        return [full_msg]

    # Split por seção
    msgs: List[str] = []
    current = header
    for section in sections:
        if len(current) + len(section) + 10 > max_chars_por_msg:
            msgs.append(current.strip())
            current = "🚨 *RESUMO DO DIA (cont.)* 🚨\n\n"
        current += section + "\n\n"
    current += footer
    msgs.append(current.strip())

    return msgs
