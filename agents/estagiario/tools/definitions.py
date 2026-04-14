"""
Tools do Estagiário v3 — Gemini Function Calling nativo.

Tools read-only para consulta ao banco de clusters + reuso das tools do Resumo.
Cada tool tem: Pydantic input schema, implementação, Gemini FunctionDeclaration.
"""

from __future__ import annotations

import json
import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

try:
    from backend.database import SessionLocal
    from backend.crud import (
        get_clusters_for_feed_by_date,
        get_cluster_details_by_id,
    )
    from backend.utils import get_date_brasil
except Exception:
    SessionLocal = None  # type: ignore
    get_clusters_for_feed_by_date = None  # type: ignore
    get_cluster_details_by_id = None  # type: ignore
    get_date_brasil = None  # type: ignore

from agents.resumo_diario.tools.definitions import (
    execute_obter_textos_brutos,
    execute_buscar_na_web,
)


def _open_db():
    if SessionLocal is None:
        raise RuntimeError("Backend indisponível")
    return SessionLocal()


# ══════════════════════════════════════════════════════════════
# Tool 1: list_cluster_titles
# ══════════════════════════════════════════════════════════════

def list_cluster_titles(db, data_str: str = "") -> List[Dict[str, Any]]:
    """Lightweight list of all clusters (id, title, tags, priority) for a given date."""
    d = _parse_date(data_str)
    page, acc = 1, []
    while True:
        resp = get_clusters_for_feed_by_date(db, d, page=page, page_size=100, load_full_text=False)
        for c in resp.get("clusters", []):
            acc.append({
                "id": c.get("id"),
                "titulo": c.get("titulo_final", ""),
                "prioridade": c.get("prioridade", ""),
                "tags": c.get("tags") or [],
                "fontes": [f.get("jornal", "") for f in (c.get("fontes") or [])[:3]],
            })
        if not resp.get("paginacao", {}).get("tem_proxima"):
            break
        page += 1
    return acc


# ══════════════════════════════════════════════════════════════
# Tool 2: query_clusters
# ══════════════════════════════════════════════════════════════

def query_clusters(
    db,
    data_str: str = "",
    prioridade: str = "",
    palavras_chave: str = "",
    limite: int = 30,
) -> List[Dict[str, Any]]:
    """Search clusters with filters (priority, keywords). Returns title + resumo."""
    d = _parse_date(data_str)
    prio = prioridade if prioridade in {"P1_CRITICO", "P2_ESTRATEGICO", "P3_MONITORAMENTO"} else None
    kws = [k.strip().lower() for k in palavras_chave.split(",") if k.strip()] if palavras_chave else []
    page, acc = 1, []
    while len(acc) < limite:
        resp = get_clusters_for_feed_by_date(
            db, d, page=page, page_size=min(100, limite - len(acc)),
            load_full_text=False, priority=prio,
        )
        clusters = resp.get("clusters", [])
        if kws:
            filtered = []
            for c in clusters:
                blob = ((c.get("titulo_final") or "") + " " + (c.get("resumo_final") or "")).lower()
                if any(k in blob for k in kws):
                    filtered.append(c)
            clusters = filtered
        for c in clusters:
            acc.append({
                "id": c.get("id"),
                "titulo": c.get("titulo_final", ""),
                "resumo": (c.get("resumo_final") or "")[:600],
                "prioridade": c.get("prioridade", ""),
                "tags": c.get("tags") or [],
                "fontes": [f.get("jornal", "") for f in (c.get("fontes") or [])[:3]],
            })
        if not resp.get("paginacao", {}).get("tem_proxima"):
            break
        page += 1
    return acc[:limite]


# ══════════════════════════════════════════════════════════════
# Tool 3: get_cluster_details
# ══════════════════════════════════════════════════════════════

def get_cluster_details(db, cluster_id: int) -> Dict[str, Any]:
    """Full details for a single cluster (articles, sources, summary)."""
    det = get_cluster_details_by_id(db, cluster_id)
    return det or {"error": f"Cluster {cluster_id} não encontrado."}


# ══════════════════════════════════════════════════════════════
# Tool 4: query_clusters_range (NEW — multi-day)
# ══════════════════════════════════════════════════════════════

_MAX_RANGE_DAYS = 7

def query_clusters_range(
    db,
    data_inicio: str,
    data_fim: str,
    palavras_chave: str = "",
    limite: int = 50,
) -> List[Dict[str, Any]]:
    """Search clusters across a date range (max 7 days). Returns title + resumo + date."""
    d_start = _parse_date(data_inicio)
    d_end = _parse_date(data_fim)
    if d_end < d_start:
        d_start, d_end = d_end, d_start
    if (d_end - d_start).days > _MAX_RANGE_DAYS:
        d_start = d_end - datetime.timedelta(days=_MAX_RANGE_DAYS)

    kws = [k.strip().lower() for k in palavras_chave.split(",") if k.strip()] if palavras_chave else []
    acc = []
    current = d_start
    while current <= d_end and len(acc) < limite:
        page = 1
        while len(acc) < limite:
            resp = get_clusters_for_feed_by_date(db, current, page=page, page_size=100, load_full_text=False)
            clusters = resp.get("clusters", [])
            if kws:
                clusters = [
                    c for c in clusters
                    if any(k in ((c.get("titulo_final") or "") + " " + (c.get("resumo_final") or "")).lower() for k in kws)
                ]
            for c in clusters:
                acc.append({
                    "id": c.get("id"),
                    "data": current.isoformat(),
                    "titulo": c.get("titulo_final", ""),
                    "resumo": (c.get("resumo_final") or "")[:400],
                    "prioridade": c.get("prioridade", ""),
                    "tags": c.get("tags") or [],
                })
            if not resp.get("paginacao", {}).get("tem_proxima"):
                break
            page += 1
        current += datetime.timedelta(days=1)
    return acc[:limite]


# ══════════════════════════════════════════════════════════════
# Tool 5 & 6: reuse from resumo agent (obter_textos_brutos, buscar_na_web)
# ══════════════════════════════════════════════════════════════
# execute_obter_textos_brutos(db, cluster_id) — imported above
# execute_buscar_na_web(query)                — imported above


# ══════════════════════════════════════════════════════════════
# Gemini FunctionDeclaration schemas
# ══════════════════════════════════════════════════════════════

def build_tool_declarations():
    """Build genai.protos.Tool with all estagiario function declarations."""
    import google.generativeai as genai  # type: ignore

    S = genai.protos.Schema
    T = genai.protos.Type
    FD = genai.protos.FunctionDeclaration

    return genai.protos.Tool(function_declarations=[
        FD(
            name="list_cluster_titles",
            description=(
                "Lista TODOS os clusters (notícias agrupadas) de uma data. "
                "Retorna id, titulo, prioridade, tags, fontes. Use PRIMEIRO para ter visão geral."
            ),
            parameters=S(type=T.OBJECT, properties={
                "data": S(type=T.STRING, description="Data no formato YYYY-MM-DD. Padrão: hoje."),
            }, required=[]),
        ),
        FD(
            name="query_clusters",
            description=(
                "Busca clusters com filtros (prioridade, palavras-chave). "
                "Retorna titulo + resumo. Útil para perguntas específicas sobre um tema."
            ),
            parameters=S(type=T.OBJECT, properties={
                "data": S(type=T.STRING, description="Data YYYY-MM-DD. Padrão: hoje."),
                "prioridade": S(type=T.STRING, description="P1_CRITICO, P2_ESTRATEGICO ou P3_MONITORAMENTO. Vazio = todas."),
                "palavras_chave": S(type=T.STRING, description="Termos separados por vírgula para filtrar titulo/resumo."),
                "limite": S(type=T.INTEGER, description="Máximo de resultados (padrão 30)."),
            }, required=[]),
        ),
        FD(
            name="get_cluster_details",
            description=(
                "Detalhes COMPLETOS de um cluster: artigos originais, resumo completo, fontes. "
                "Use para aprofundar clusters específicos após identificá-los."
            ),
            parameters=S(type=T.OBJECT, properties={
                "cluster_id": S(type=T.INTEGER, description="ID numérico do cluster."),
            }, required=["cluster_id"]),
        ),
        FD(
            name="query_clusters_range",
            description=(
                "Busca clusters em um INTERVALO de datas (máx 7 dias). "
                "Útil para perguntas temporais: 'o que aconteceu com X esta semana?', "
                "'compare ontem com hoje', 'evolução do caso Y nos últimos dias'."
            ),
            parameters=S(type=T.OBJECT, properties={
                "data_inicio": S(type=T.STRING, description="Data inicial YYYY-MM-DD."),
                "data_fim": S(type=T.STRING, description="Data final YYYY-MM-DD."),
                "palavras_chave": S(type=T.STRING, description="Termos separados por vírgula."),
                "limite": S(type=T.INTEGER, description="Máximo de resultados (padrão 50)."),
            }, required=["data_inicio", "data_fim"]),
        ),
        FD(
            name="obter_textos_brutos_cluster",
            description=(
                "Retorna os textos ORIGINAIS (até 3000 chars cada) dos artigos de um cluster. "
                "Use para extrair dados factuais críticos (valores R$, nomes, datas, tribunais) "
                "que estejam ausentes no resumo."
            ),
            parameters=S(type=T.OBJECT, properties={
                "cluster_id": S(type=T.INTEGER, description="ID do cluster para aprofundar."),
            }, required=["cluster_id"]),
        ),
        FD(
            name="buscar_na_web",
            description=(
                "Busca informações na web em tempo real. Use para dados atualizados "
                "(cotações, decisões recentes) não presentes nos clusters. Máximo 2 buscas por sessão."
            ),
            parameters=S(type=T.OBJECT, properties={
                "query": S(type=T.STRING, description="Termo de busca (ex: 'Braskem recuperação judicial 2026')."),
            }, required=["query"]),
        ),
    ])


# ══════════════════════════════════════════════════════════════
# Dispatcher — maps tool name → execution function
# ══════════════════════════════════════════════════════════════

def dispatch_tool(db, tool_name: str, args: dict) -> Any:
    """Execute a tool by name. All tools are read-only."""
    if tool_name == "list_cluster_titles":
        return list_cluster_titles(db, data_str=args.get("data", ""))

    if tool_name == "query_clusters":
        return query_clusters(
            db,
            data_str=args.get("data", ""),
            prioridade=args.get("prioridade", ""),
            palavras_chave=args.get("palavras_chave", ""),
            limite=int(args.get("limite", 30)),
        )

    if tool_name == "get_cluster_details":
        return get_cluster_details(db, cluster_id=int(args.get("cluster_id", 0)))

    if tool_name == "query_clusters_range":
        return query_clusters_range(
            db,
            data_inicio=args.get("data_inicio", ""),
            data_fim=args.get("data_fim", ""),
            palavras_chave=args.get("palavras_chave", ""),
            limite=int(args.get("limite", 50)),
        )

    if tool_name == "obter_textos_brutos_cluster":
        return execute_obter_textos_brutos(db, cluster_id=int(args.get("cluster_id", 0)))

    if tool_name == "buscar_na_web":
        return execute_buscar_na_web(query=str(args.get("query", "")))

    return {"error": f"Tool '{tool_name}' não reconhecida."}


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _parse_date(s: str) -> datetime.date:
    if s:
        try:
            return datetime.datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    return get_date_brasil() if get_date_brasil else datetime.date.today()
