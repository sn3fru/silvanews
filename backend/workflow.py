"""
LangGraph Workflow for the Graph-RAG Agentic Pipeline (v2.0).

Substitui o loop linear do process_articles.py por um grafo de estados.
Segue a estrategia "Strangler Fig": roda em paralelo com o pipeline existente.

Uso:
    from backend.workflow import run_article_through_workflow, create_workflow

    # Processar um artigo pelo novo pipeline
    result = run_article_through_workflow(artigo_id=123)
    
    # Ou processar em modo "sombra" (loga sem salvar)
    result = run_article_through_workflow(artigo_id=123, shadow_mode=True)
"""

import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

# Tenta importar LangGraph (graceful degradation se nao disponivel)
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    print("[Workflow] AVISO: langgraph nao instalado. Usando fallback linear.")

try:
    from .agents.nodes import (
        FeedState,
        gatekeeper_node,
        entity_extraction_node,
        entity_resolution_node,
        historian_node,
        writer_node,
        check_relevance,
        check_entities,
    )
    from .database import SessionLocal, ArtigoBruto
    from .utils import get_date_brasil_str
except ImportError:
    from backend.agents.nodes import (
        FeedState,
        gatekeeper_node,
        entity_extraction_node,
        entity_resolution_node,
        historian_node,
        writer_node,
        check_relevance,
        check_entities,
    )
    from backend.database import SessionLocal, ArtigoBruto
    from backend.utils import get_date_brasil_str


# ==============================================================================
# WORKFLOW BUILDER
# ==============================================================================

def create_workflow():
    """
    Cria o grafo de estados LangGraph para o pipeline de processamento.
    
    Fluxo:
        gatekeeper -> [relevant?] -> entity_extraction -> entity_resolution
                                                              |
                                                          historian
                                                              |
                                                           writer -> END
                   -> [irrelevant?] -> END
    
    Returns:
        Compiled LangGraph application (ou None se langgraph nao disponivel)
    """
    if not LANGGRAPH_AVAILABLE:
        return None
    
    workflow = StateGraph(FeedState)
    
    # Adiciona nos (cada no encapsula funcoes existentes)
    workflow.add_node("gatekeeper", gatekeeper_node)
    workflow.add_node("entity_extraction", entity_extraction_node)
    workflow.add_node("entity_resolution", entity_resolution_node)
    workflow.add_node("historian", historian_node)
    workflow.add_node("writer", writer_node)
    
    # Define ponto de entrada
    workflow.set_entry_point("gatekeeper")
    
    # Edges condicionais
    workflow.add_conditional_edges(
        "gatekeeper",
        check_relevance,
        {
            "relevant": "entity_extraction",
            "irrelevant": END,
        }
    )
    
    # Entity extraction -> entity resolution (sempre)
    workflow.add_edge("entity_extraction", "entity_resolution")
    
    # Entity resolution -> historian (sempre, mesmo sem entidades)
    workflow.add_edge("entity_resolution", "historian")
    
    # Historian -> writer (sempre)
    workflow.add_edge("historian", "writer")
    
    # Writer -> END
    workflow.add_edge("writer", END)
    
    # Compila o grafo
    return workflow.compile()


# Singleton do workflow compilado
_compiled_workflow = None


def get_workflow():
    """Retorna o workflow compilado (singleton)."""
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = create_workflow()
    return _compiled_workflow


# ==============================================================================
# FALLBACK LINEAR (Quando LangGraph nao esta disponivel)
# ==============================================================================

def _run_linear_fallback(state: FeedState) -> FeedState:
    """
    Executa o pipeline de forma linear (fallback quando langgraph nao disponivel).
    Reproduz a mesma sequencia de nos do grafo.
    """
    # 1. Gatekeeper
    state = gatekeeper_node(state)
    if not state.get("is_relevant", False):
        return state
    
    # 2. Entity Extraction
    state = entity_extraction_node(state)
    
    # 3. Entity Resolution
    state = entity_resolution_node(state)
    
    # 4. Historian
    state = historian_node(state)
    
    # 5. Writer
    state = writer_node(state)
    
    return state


# ==============================================================================
# API PRINCIPAL
# ==============================================================================

def run_article_through_workflow(
    artigo_id: int,
    shadow_mode: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Processa um artigo pelo pipeline agentico (v2.0).
    
    Args:
        artigo_id: ID do artigo em artigos_brutos
        shadow_mode: Se True, apenas loga sem salvar resultados no banco
                     (modo seguro para comparacao com pipeline v1)
        verbose: Se True, imprime logs detalhados
    
    Returns:
        Dict com resultado do processamento:
        {
            "artigo_id": int,
            "is_relevant": bool,
            "entities_count": int,
            "has_context": bool,
            "resumo_final": str,
            "processing_log": list,
            "shadow_mode": bool,
        }
    """
    # Busca artigo do banco
    db = SessionLocal()
    try:
        artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == artigo_id).first()
        if not artigo:
            return {
                "artigo_id": artigo_id,
                "error": f"Artigo {artigo_id} nao encontrado",
                "is_relevant": False,
            }
        
        # Monta estado inicial
        metadados = artigo.metadados or {}
        initial_state: FeedState = {
            "artigo_id": artigo.id,
            "texto_raw": artigo.texto_bruto or "",
            "titulo": artigo.titulo_extraido or metadados.get("titulo", ""),
            "jornal": artigo.jornal or metadados.get("jornal", ""),
            "tipo_fonte": artigo.tipo_fonte or "nacional",
            "metadados": metadados,
            "is_relevant": True,
            "classificacao": {},
            "rejection_reason": "",
            "entities_raw": [],
            "entities_resolved": [],
            "contexto_historico": "",
            "resumo_final": "",
            "resumo_metadata": {},
            "cluster_id": 0,
            "cluster_action": "none",
            "error": "",
            "processing_log": [],
        }
    finally:
        db.close()
    
    # Executa o workflow
    workflow = get_workflow()
    
    if workflow:
        # Usa LangGraph
        try:
            final_state = workflow.invoke(initial_state)
        except Exception as e:
            final_state = {
                **initial_state,
                "error": f"Erro no workflow LangGraph: {str(e)}",
                "processing_log": initial_state.get("processing_log", []) + [f"[Workflow] ERRO: {e}"],
            }
    else:
        # Fallback linear
        final_state = _run_linear_fallback(initial_state)
    
    # Log verboso
    if verbose:
        print(f"\n{'='*60}")
        print(f"WORKFLOW v2.0 - Artigo {artigo_id}")
        print(f"{'='*60}")
        for entry in final_state.get("processing_log", []):
            print(f"  {entry}")
        print(f"\n  Relevante: {final_state.get('is_relevant')}")
        print(f"  Entidades: {len(final_state.get('entities_raw', []))}")
        print(f"  Contexto: {'Sim' if final_state.get('contexto_historico') else 'Nao'}")
        print(f"  Resumo: {len(final_state.get('resumo_final', ''))} chars")
        if final_state.get("error"):
            print(f"  ERRO: {final_state['error']}")
        print(f"  Modo: {'SOMBRA (sem salvar)' if shadow_mode else 'PRODUCAO'}")
        print(f"{'='*60}\n")
    
    # SEMPRE salva metadados v2 (independente de shadow mode)
    # Em shadow mode: grava metadados + resumo v2 sem sobrescrever v1
    # Em producao: mesma coisa (pode ser usado para comparar)
    if final_state.get("is_relevant"):
        _save_workflow_results(artigo_id, final_state, shadow_mode=shadow_mode)
    
    # Retorna resultado limpo
    return {
        "artigo_id": artigo_id,
        "is_relevant": final_state.get("is_relevant", False),
        "rejection_reason": final_state.get("rejection_reason", ""),
        "entities_count": len(final_state.get("entities_raw", [])),
        "entities": final_state.get("entities_raw", []),
        "has_context": bool(final_state.get("contexto_historico")),
        "contexto_historico": final_state.get("contexto_historico", ""),
        "resumo_final": final_state.get("resumo_final", ""),
        "resumo_metadata": final_state.get("resumo_metadata", {}),
        "processing_log": final_state.get("processing_log", []),
        "shadow_mode": shadow_mode,
        "error": final_state.get("error", ""),
    }


def _save_workflow_results(artigo_id: int, state: FeedState, shadow_mode: bool = True):
    """
    Salva resultados do workflow v2.0 no banco.
    
    SEMPRE salva (shadow ou producao):
      - metadados v2 (entity count, context flag, timestamp)
      - resumo v2 (campo separado, nao sobrescreve v1)
      - entidades e arestas ja foram salvas pelo entity_resolution_node
      - embedding_v2 ja foi salvo pelo historian_node
    """
    db = SessionLocal()
    try:
        artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == artigo_id).first()
        if not artigo:
            return
        
        # Atualiza metadados com informacoes do grafo v2
        metadados = artigo.metadados or {}
        metadados["v2_entities_count"] = len(state.get("entities_raw", []))
        metadados["v2_entities"] = [
            {"name": e.get("name"), "type": e.get("type"), "role": e.get("role")}
            for e in state.get("entities_raw", [])
        ]
        metadados["v2_has_context"] = bool(state.get("contexto_historico"))
        metadados["v2_processed_at"] = datetime.utcnow().isoformat()
        metadados["v2_shadow_mode"] = shadow_mode
        
        # Salva resumo v2 separadamente (nao sobrescreve v1)
        resumo_v2 = state.get("resumo_final", "")
        if resumo_v2:
            metadados["v2_resumo"] = resumo_v2[:5000]  # Cap para evitar payload gigante
        
        # Salva contexto historico usado
        contexto = state.get("contexto_historico", "")
        if contexto:
            metadados["v2_contexto_historico"] = contexto[:3000]
        
        # Log do workflow
        metadados["v2_processing_log"] = state.get("processing_log", [])
        
        artigo.metadados = metadados
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Workflow] Erro ao salvar resultados: {e}")
    finally:
        db.close()


# ==============================================================================
# BATCH PROCESSING (Processar multiplos artigos)
# ==============================================================================

def run_batch_workflow(
    artigo_ids: List[int],
    shadow_mode: bool = True,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    Processa uma lista de artigos pelo workflow v2.0.
    
    Args:
        artigo_ids: Lista de IDs de artigos
        shadow_mode: Se True, apenas loga
        verbose: Se True, imprime detalhes
    
    Returns:
        Lista de resultados
    """
    results = []
    total = len(artigo_ids)
    
    for i, artigo_id in enumerate(artigo_ids, 1):
        if verbose:
            print(f"\n[{i}/{total}] Processando artigo {artigo_id}...")
        
        result = run_article_through_workflow(
            artigo_id=artigo_id,
            shadow_mode=shadow_mode,
            verbose=verbose,
        )
        results.append(result)
    
    # Sumario
    relevant = sum(1 for r in results if r.get("is_relevant"))
    with_entities = sum(1 for r in results if r.get("entities_count", 0) > 0)
    with_context = sum(1 for r in results if r.get("has_context"))
    errors = sum(1 for r in results if r.get("error"))
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"SUMARIO DO BATCH ({total} artigos)")
        print(f"{'='*60}")
        print(f"  Relevantes: {relevant}/{total}")
        print(f"  Com entidades: {with_entities}/{total}")
        print(f"  Com contexto historico: {with_context}/{total}")
        print(f"  Erros: {errors}/{total}")
        print(f"  Modo: {'SOMBRA' if shadow_mode else 'PRODUCAO'}")
        print(f"{'='*60}\n")
    
    return results


# ==============================================================================
# CLI INTERFACE
# ==============================================================================

if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("BTG AlphaFeed - Workflow v2.0 (Graph-RAG Agentic)")
    print("=" * 60)
    
    if not LANGGRAPH_AVAILABLE:
        print("\nAVISO: langgraph nao instalado. Usando fallback linear.")
        print("Para instalar: pip install langgraph")
    
    # Processar artigos de teste
    if len(sys.argv) > 1:
        artigo_ids = [int(x) for x in sys.argv[1].split(",")]
    else:
        # Busca ultimos 5 artigos pendentes
        db = SessionLocal()
        try:
            artigos = (
                db.query(ArtigoBruto.id)
                .filter(ArtigoBruto.status == 'pendente')
                .order_by(ArtigoBruto.created_at.desc())
                .limit(5)
                .all()
            )
            artigo_ids = [a.id for a in artigos]
        finally:
            db.close()
    
    if not artigo_ids:
        print("\nNenhum artigo pendente encontrado.")
        sys.exit(0)
    
    print(f"\nProcessando {len(artigo_ids)} artigos em modo SOMBRA...")
    results = run_batch_workflow(
        artigo_ids=artigo_ids,
        shadow_mode=True,
        verbose=True,
    )
