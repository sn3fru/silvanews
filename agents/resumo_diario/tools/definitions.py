"""
Definições de Tools e Contratos Pydantic para o Agente de Resumo Diário (WhatsApp).

Contém:
- Modelos Pydantic (ClusterSelecionado, ResumoDiarioContract) para validação do JSON de saída do LLM.
- Schema Gemini Function Calling para tools: obter_textos_brutos_cluster, buscar_na_web (Tivaly).
- Funções de execução (wrappers READ-ONLY com hard-limits).
"""

import os
from pydantic import BaseModel, Field, conlist
from typing import Dict, Any, List, Literal, Optional

try:
    from backend.database import SessionLocal
    from backend.crud import get_textos_brutos_por_cluster_id
except Exception:
    SessionLocal = None  # type: ignore
    get_textos_brutos_por_cluster_id = None  # type: ignore


# ==============================================================================
# MODELOS PYDANTIC — Contrato de saída do LLM
# ==============================================================================

class ClusterSelecionado(BaseModel):
    cluster_id: int
    secao: Literal["foco_analista", "distressed", "estrategico", "regulatorio", "internacional"] = Field(
        "distressed",
        description="Seção temática obrigatória."
    )
    titulo_whatsapp: str = Field(
        ...,
        max_length=100,
        description="Título curto com emoji. Máximo 100 caracteres."
    )
    bullet_impacto: str = Field(
        ...,
        max_length=280,
        description="Frase única, concisa, direto ao impacto financeiro/legal."
    )
    fonte_principal: str = Field(..., max_length=80)


class ResumoDiarioContract(BaseModel):
    tldr_executivo: Optional[str] = Field(
        None,
        max_length=500,
        description="2-3 frases, panorama geral do dia."
    )
    clusters_selecionados: conlist(ClusterSelecionado, min_length=1, max_length=15) = Field(
        ...,
        description="Lista de oportunidades, 1 a 15 itens."
    )


# ==============================================================================
# SCHEMA GEMINI FUNCTION CALLING — Tool obter_textos_brutos_cluster
# ==============================================================================

TOOL_OBTER_TEXTOS_BRUTOS_SCHEMA = {
    "name": "obter_textos_brutos_cluster",
    "description": (
        "Retorna uma amostra (primeiros 3000 caracteres) dos textos originais de um cluster. "
        "ATENÇÃO: Use esta ferramenta EXCLUSIVAMENTE para extrair dados factuais críticos "
        "(valores, nomes próprios, datas específicas, varas judiciais) que estão ausentes no "
        "resumo do contexto inicial. O uso exploratório ou redundante desta ferramenta é "
        "estritamente proibido."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "cluster_id": {
                "type": "INTEGER",
                "description": "O ID numérico do cluster (evento) que requer aprofundamento factual."
            }
        },
        "required": ["cluster_id"]
    }
}

# Hard-limit de caracteres por artigo ao retornar textos brutos (previne estouro de contexto)
_TEXTO_BRUTO_CHAR_LIMIT = 3000


# ==============================================================================
# SCHEMA GEMINI FUNCTION CALLING — Tool buscar_na_web (Tivaly)
# ==============================================================================

TOOL_BUSCAR_NA_WEB_SCHEMA = {
    "name": "buscar_na_web",
    "description": (
        "Busca informações na web em tempo real sobre um tema específico. "
        "Use para complementar o contexto com dados atualizados (cotações, "
        "decisões judiciais recentes, notícias de última hora) que não estejam "
        "nos clusters do dia. ATENÇÃO: Use com parcimônia — máximo 2 buscas por "
        "sessão. Retorna os 3 resultados mais relevantes."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Termo de busca para pesquisa na web (ex: 'OI S.A. recuperação judicial 2025')"
            }
        },
        "required": ["query"]
    }
}


def execute_buscar_na_web(query: str) -> Dict[str, Any]:
    """
    Executa busca na web via Tivaly API.
    Placeholder: retorna erro amigável até que a TIVALY_API_KEY seja configurada.
    """
    api_key = os.getenv("TIVALY_API_KEY")
    if not api_key:
        return {
            "status": "unavailable",
            "message": "Busca web desabilitada. TIVALY_API_KEY não configurada no ambiente.",
            "results": []
        }

    try:
        import requests
        resp = requests.post(
            "https://api.tivaly.com/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": 3, "language": "pt-BR"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get("results", [])[:3]:
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", "")[:500],
                    "url": r.get("url", ""),
                })
            return {"status": "ok", "results": results}
        else:
            return {"status": "error", "message": f"Tivaly API status {resp.status_code}", "results": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "results": []}


# ==============================================================================
# EXECUÇÃO DAS TOOLS — Wrappers READ-ONLY
# ==============================================================================

def execute_obter_textos_brutos(db, cluster_id: int) -> List[Dict[str, Any]]:
    """
    Executa a tool `obter_textos_brutos_cluster`:
    - Chama `get_textos_brutos_por_cluster_id` do CRUD existente.
    - Aplica hard-limit de _TEXTO_BRUTO_CHAR_LIMIT por artigo.
    - Retorna lista de dicts com id, titulo, fonte e texto_bruto (truncado).
    """
    if get_textos_brutos_por_cluster_id is None:
        return [{"error": "CRUD indisponível — backend não configurado."}]

    try:
        textos = get_textos_brutos_por_cluster_id(db, cluster_id)
        resultado: List[Dict[str, Any]] = []
        for t in textos:
            resultado.append({
                "id": t.get("id"),
                "titulo": t.get("titulo", "Sem título"),
                "fonte": t.get("fonte", "Fonte desconhecida"),
                "texto_bruto": (t.get("texto_bruto") or "")[:_TEXTO_BRUTO_CHAR_LIMIT]
            })
        return resultado
    except Exception as e:
        return [{"error": f"Falha ao buscar textos brutos do cluster {cluster_id}: {e}"}]
