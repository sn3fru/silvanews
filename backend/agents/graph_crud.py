"""
CRUD operations for the Knowledge Graph (graph_entities + graph_edges).
Handles Entity Resolution, edge creation, and graph queries.
"""

import re
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func, text, and_, or_, desc

try:
    from ..database import GraphEntity, GraphEdge, ArtigoBruto, ClusterEvento, SessionLocal
except ImportError:
    from backend.database import GraphEntity, GraphEdge, ArtigoBruto, ClusterEvento, SessionLocal


# ==============================================================================
# ENTITY RESOLUTION (Normalizacao de Entidades)
# ==============================================================================

# Mapeamento de aliases conhecidos para canonical_name
KNOWN_ALIASES = {
    # Politicos / Governo
    "lula": "Luiz Inacio Lula da Silva",
    "presidente lula": "Luiz Inacio Lula da Silva",
    "luiz inacio": "Luiz Inacio Lula da Silva",
    "haddad": "Fernando Haddad",
    "fernando haddad": "Fernando Haddad",
    "ministro haddad": "Fernando Haddad",
    "galipolo": "Gabriel Galipolo",
    "gabriel galipolo": "Gabriel Galipolo",
    "campos neto": "Roberto Campos Neto",
    "roberto campos neto": "Roberto Campos Neto",
    "tarcisio": "Tarcisio de Freitas",
    "tarcisio de freitas": "Tarcisio de Freitas",
    # Orgaos
    "bc": "Banco Central do Brasil",
    "bacen": "Banco Central do Brasil",
    "banco central": "Banco Central do Brasil",
    "cvm": "Comissao de Valores Mobiliarios",
    "stf": "Supremo Tribunal Federal",
    "stj": "Superior Tribunal de Justica",
    "carf": "Conselho Administrativo de Recursos Fiscais",
    "pgfn": "Procuradoria-Geral da Fazenda Nacional",
    "receita federal": "Receita Federal do Brasil",
    "bndes": "Banco Nacional de Desenvolvimento",
    "anatel": "Agencia Nacional de Telecomunicacoes",
    "aneel": "Agencia Nacional de Energia Eletrica",
    "ans": "Agencia Nacional de Saude Suplementar",
    "anvisa": "Agencia Nacional de Vigilancia Sanitaria",
    # Empresas comuns
    "petrobras": "Petrobras S.A.",
    "vale": "Vale S.A.",
    "itau": "Itau Unibanco S.A.",
    "itau unibanco": "Itau Unibanco S.A.",
    "bradesco": "Bradesco S.A.",
    "btg": "BTG Pactual",
    "btg pactual": "BTG Pactual",
    "americanas": "Americanas S.A.",
    "oi": "Oi S.A.",
    "gol": "GOL Linhas Aereas",
    "azul": "Azul S.A.",
    "latam": "LATAM Airlines",
    "jbs": "JBS S.A.",
    "ambev": "Ambev S.A.",
    "eletrobras": "Eletrobras S.A.",
    "sabesp": "Sabesp S.A.",
}


def _normalize_name(name: str) -> str:
    """Normaliza um nome para comparacao (lowercase, sem acentos, sem pontuacao extra)."""
    name = name.strip().lower()
    # Remove acentos simples
    replacements = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a',
        'é': 'e', 'ê': 'e', 'è': 'e',
        'í': 'i', 'î': 'i',
        'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ú': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c',
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    # Remove pontuacao
    name = re.sub(r'[^\w\s]', '', name)
    # Remove espacos extras
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def resolve_canonical_name(name: str) -> str:
    """Resolve o nome canonico de uma entidade usando aliases conhecidos."""
    normalized = _normalize_name(name)
    if normalized in KNOWN_ALIASES:
        return KNOWN_ALIASES[normalized]
    # Se nao encontrar alias, retorna o nome com primeira letra maiuscula
    return name.strip().title()


def find_entity_by_name(
    db: Session,
    name: str,
    entity_type: Optional[str] = None,
    similarity_threshold: float = 0.6
) -> Optional[GraphEntity]:
    """
    Busca uma entidade existente por nome, usando resolucao canonica e busca fuzzy.
    
    Args:
        db: Sessao do banco
        name: Nome da entidade
        entity_type: Tipo (PERSON, ORG, GOV, EVENT, CONCEPT)
        similarity_threshold: Limiar para busca fuzzy (0-1)
    
    Returns:
        Entidade encontrada ou None
    """
    canonical = resolve_canonical_name(name)
    
    # 1. Busca exata por canonical_name
    query = db.query(GraphEntity).filter(
        func.lower(GraphEntity.canonical_name) == canonical.lower()
    )
    if entity_type:
        query = query.filter(GraphEntity.entity_type == entity_type)
    
    entity = query.first()
    if entity:
        return entity
    
    # 2. Busca por nome original
    query = db.query(GraphEntity).filter(
        func.lower(GraphEntity.name) == name.strip().lower()
    )
    if entity_type:
        query = query.filter(GraphEntity.entity_type == entity_type)
    
    entity = query.first()
    if entity:
        return entity
    
    # 3. Busca fuzzy com trigram (se disponivel)
    try:
        query = db.query(GraphEntity).filter(
            func.similarity(GraphEntity.canonical_name, canonical) > similarity_threshold
        )
        if entity_type:
            query = query.filter(GraphEntity.entity_type == entity_type)
        
        entity = query.order_by(
            func.similarity(GraphEntity.canonical_name, canonical).desc()
        ).first()
        
        if entity:
            return entity
    except Exception:
        # Trigram nao disponivel, ignora
        pass
    
    return None


def get_or_create_entity(
    db: Session,
    name: str,
    entity_type: str,
    description: Optional[str] = None
) -> GraphEntity:
    """
    Busca ou cria uma entidade no grafo, com resolucao de nomes.
    
    Args:
        db: Sessao do banco
        name: Nome da entidade
        entity_type: PERSON, ORG, GOV, EVENT, CONCEPT
        description: Descricao opcional
    
    Returns:
        Entidade existente ou recem-criada
    """
    # Tenta encontrar existente
    entity = find_entity_by_name(db, name, entity_type)
    if entity:
        # Atualiza aliases se nome diferente
        normalized = _normalize_name(name)
        canonical_normalized = _normalize_name(entity.canonical_name)
        if normalized != canonical_normalized:
            aliases = entity.aliases or []
            if name.strip() not in aliases:
                aliases.append(name.strip())
                entity.aliases = aliases
                entity.updated_at = datetime.utcnow()
                db.commit()
        return entity
    
    # Cria nova entidade
    canonical = resolve_canonical_name(name)
    entity = GraphEntity(
        name=name.strip(),
        canonical_name=canonical,
        entity_type=entity_type.upper(),
        description=description,
        aliases=[name.strip()] if name.strip().lower() != canonical.lower() else []
    )
    
    try:
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity
    except Exception as e:
        db.rollback()
        # Em caso de race condition (unique constraint), busca de novo
        entity = find_entity_by_name(db, name, entity_type)
        if entity:
            return entity
        raise e


# ==============================================================================
# EDGE OPERATIONS (Arestas do Grafo)
# ==============================================================================

def create_edge(
    db: Session,
    artigo_id: int,
    entity_id: uuid.UUID,
    relation_type: str = "MENTIONED",
    sentiment_score: Optional[float] = None,
    context_snippet: Optional[str] = None,
    confidence: float = 1.0
) -> Optional[GraphEdge]:
    """
    Cria uma aresta ligando um artigo a uma entidade.
    Idempotente: se ja existir, retorna a existente.
    """
    # Verifica se ja existe
    existing = db.query(GraphEdge).filter(
        GraphEdge.artigo_id == artigo_id,
        GraphEdge.entity_id == entity_id
    ).first()
    
    if existing:
        # Atualiza se dados novos forem melhores
        if sentiment_score is not None and existing.sentiment_score is None:
            existing.sentiment_score = sentiment_score
        if context_snippet and not existing.context_snippet:
            existing.context_snippet = context_snippet
        if confidence > (existing.confidence or 0):
            existing.confidence = confidence
        db.commit()
        return existing
    
    edge = GraphEdge(
        artigo_id=artigo_id,
        entity_id=entity_id,
        relation_type=relation_type.upper(),
        sentiment_score=sentiment_score,
        context_snippet=context_snippet[:500] if context_snippet else None,
        confidence=confidence
    )
    
    try:
        db.add(edge)
        db.commit()
        db.refresh(edge)
        return edge
    except Exception as e:
        db.rollback()
        print(f"Erro ao criar edge artigo={artigo_id} entity={entity_id}: {e}")
        return None


def link_artigo_to_entities(
    db: Session,
    artigo_id: int,
    entities: List[Dict[str, Any]]
) -> List[GraphEdge]:
    """
    Liga um artigo a multiplas entidades (batch).
    
    Args:
        db: Sessao do banco
        artigo_id: ID do artigo
        entities: Lista de dicts com keys: name, type, role, sentiment, context
    
    Returns:
        Lista de edges criadas
    """
    edges = []
    for ent_data in entities:
        name = ent_data.get("name", "").strip()
        if not name or len(name) < 2:
            continue
        
        entity_type = ent_data.get("type", "ORG").upper()
        if entity_type not in ("PERSON", "ORG", "GOV", "EVENT", "CONCEPT"):
            entity_type = "ORG"
        
        # Get or create entity
        entity = get_or_create_entity(db, name, entity_type)
        
        # Create edge
        edge = create_edge(
            db=db,
            artigo_id=artigo_id,
            entity_id=entity.id,
            relation_type=ent_data.get("role", "MENTIONED"),
            sentiment_score=ent_data.get("sentiment"),
            context_snippet=ent_data.get("context"),
            confidence=ent_data.get("confidence", 1.0)
        )
        
        if edge:
            edges.append(edge)
    
    return edges


# ==============================================================================
# GRAPH QUERIES (Consultas ao Grafo)
# ==============================================================================

def get_entity_history(
    db: Session,
    entity_id: uuid.UUID,
    days: int = 7,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Busca historico recente de uma entidade (ultimos N dias).
    Retorna resumos de clusters conectados.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # CORRECAO: Join order corrigido. Antes referenciava ArtigoBruto.id
    # na primeira join antes de ArtigoBruto estar no FROM, gerando SQL invalido
    # que corrompia a transacao PostgreSQL silenciosamente.
    results = (
        db.query(
            ClusterEvento.id,
            ClusterEvento.titulo_cluster,
            ClusterEvento.resumo_cluster,
            ClusterEvento.prioridade,
            ClusterEvento.tag,
            ClusterEvento.created_at,
            GraphEdge.relation_type,
            GraphEdge.sentiment_score,
        )
        .join(ArtigoBruto, ArtigoBruto.cluster_id == ClusterEvento.id)
        .join(GraphEdge, GraphEdge.artigo_id == ArtigoBruto.id)
        .filter(
            GraphEdge.entity_id == entity_id,
            ClusterEvento.created_at >= cutoff,
            ClusterEvento.status == 'ativo',
        )
        .group_by(ClusterEvento.id, GraphEdge.relation_type, GraphEdge.sentiment_score)
        .order_by(desc(ClusterEvento.created_at))
        .limit(limit)
        .all()
    )
    
    return [
        {
            "cluster_id": r[0],
            "titulo": r[1],
            "resumo": r[2],
            "prioridade": r[3],
            "tag": r[4],
            "data": r[5].isoformat() if r[5] else None,
            "role": r[6],
            "sentiment": r[7],
        }
        for r in results
    ]


def get_related_entities(
    db: Session,
    entity_id: uuid.UUID,
    days: int = 30,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Busca entidades que co-ocorrem com uma entidade dada.
    (Aparecem nos mesmos artigos nos ultimos N dias)
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Subquery: artigos conectados a entidade
    artigo_ids = (
        db.query(GraphEdge.artigo_id)
        .filter(GraphEdge.entity_id == entity_id)
        .join(ArtigoBruto, ArtigoBruto.id == GraphEdge.artigo_id)
        .filter(ArtigoBruto.created_at >= cutoff)
        .subquery()
    )
    
    # Busca outras entidades nesses artigos
    results = (
        db.query(
            GraphEntity.id,
            GraphEntity.canonical_name,
            GraphEntity.entity_type,
            func.count(GraphEdge.id).label("co_occurrences"),
        )
        .join(GraphEdge, GraphEdge.entity_id == GraphEntity.id)
        .filter(
            GraphEdge.artigo_id.in_(artigo_ids),
            GraphEntity.id != entity_id,
        )
        .group_by(GraphEntity.id)
        .order_by(desc("co_occurrences"))
        .limit(limit)
        .all()
    )
    
    return [
        {
            "entity_id": str(r[0]),
            "name": r[1],
            "type": r[2],
            "co_occurrences": r[3],
        }
        for r in results
    ]


def get_historical_context_for_entities(
    db: Session,
    entity_names: List[str],
    days: int = 7,
    max_results: int = 5
) -> str:
    """
    Busca contexto historico para uma lista de entidades.
    Retorna texto formatado para injecao no prompt de resumo.
    
    Este e o metodo central do "Cerebro Temporal" (Historian Node).
    """
    if not entity_names:
        return ""
    
    context_parts = []
    seen_clusters = set()
    
    for name in entity_names[:5]:  # Limita a 5 entidades para performance
        entity = find_entity_by_name(db, name)
        if not entity:
            continue
        
        history = get_entity_history(db, entity.id, days=days, limit=max_results)
        
        for item in history:
            cluster_id = item["cluster_id"]
            if cluster_id in seen_clusters:
                continue
            seen_clusters.add(cluster_id)
            
            resumo = item.get("resumo") or item.get("titulo", "")
            if resumo:
                data_str = item.get("data", "data desconhecida")
                prioridade = item.get("prioridade", "")
                context_parts.append(
                    f"[{data_str}] ({prioridade}) {resumo[:300]}"
                )
    
    if not context_parts:
        return ""
    
    header = "=== CONTEXTO HISTORICO RECUPERADO ===\n"
    header += "Os seguintes eventos recentes envolvem as mesmas entidades:\n\n"
    
    return header + "\n\n".join(context_parts[:10])


def get_similar_articles_by_embedding(
    db: Session,
    embedding_bytes: bytes,
    days: int = 30,
    top_k: int = 5,
    similarity_threshold: float = 0.7,
    exclude_artigo_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Busca vetorial: encontra artigos semanticamente similares via embedding_v2.
    Como pgvector nao esta disponivel, carrega embeddings recentes e calcula
    similaridade cosseno em Python.
    
    Args:
        db: Sessao do banco
        embedding_bytes: Embedding do artigo atual (BYTEA, float32)
        days: Janela temporal (ultimos N dias)
        top_k: Maximo de resultados
        similarity_threshold: Limiar minimo de similaridade
        exclude_artigo_id: ID do artigo atual (para excluir da busca)
    
    Returns:
        Lista de dicts com artigos similares e score
    """
    import numpy as np
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Carrega artigos recentes que tem embedding_v2
    query = (
        db.query(
            ArtigoBruto.id,
            ArtigoBruto.titulo_extraido,
            ArtigoBruto.tag,
            ArtigoBruto.prioridade,
            ArtigoBruto.cluster_id,
            ArtigoBruto.embedding_v2,
        )
        .filter(
            ArtigoBruto.embedding_v2.isnot(None),
            ArtigoBruto.created_at >= cutoff,
            ArtigoBruto.status.in_(['processado', 'pronto_agrupar']),
        )
    )
    if exclude_artigo_id:
        query = query.filter(ArtigoBruto.id != exclude_artigo_id)
    
    artigos = query.limit(2000).all()  # Cap para performance
    
    if not artigos:
        return []
    
    # Converte embedding atual
    try:
        current_emb = np.frombuffer(embedding_bytes, dtype=np.float32)
        if len(current_emb) == 0:
            return []
        norm_current = np.linalg.norm(current_emb)
        if norm_current == 0:
            return []
        current_emb = current_emb / norm_current
    except Exception:
        return []
    
    # Calcula similaridade com cada artigo
    results = []
    for artigo in artigos:
        try:
            other_emb = np.frombuffer(artigo.embedding_v2, dtype=np.float32)
            if len(other_emb) != len(current_emb):
                continue
            norm_other = np.linalg.norm(other_emb)
            if norm_other == 0:
                continue
            other_emb = other_emb / norm_other
            
            similarity = float(np.dot(current_emb, other_emb))
            
            if similarity >= similarity_threshold:
                results.append({
                    "artigo_id": artigo.id,
                    "titulo": artigo.titulo_extraido or "",
                    "tag": artigo.tag,
                    "prioridade": artigo.prioridade,
                    "cluster_id": artigo.cluster_id,
                    "similarity": round(similarity, 4),
                })
        except Exception:
            continue
    
    # Ordena por similaridade e retorna top_k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


def get_vector_context_for_article(
    db: Session,
    embedding_bytes: bytes,
    artigo_id: int,
    days: int = 30,
    max_results: int = 5,
) -> str:
    """
    Busca contexto via similaridade vetorial para injecao no prompt do Writer.
    Complementa o contexto temporal do Historian.
    """
    similar = get_similar_articles_by_embedding(
        db=db,
        embedding_bytes=embedding_bytes,
        days=days,
        top_k=max_results,
        similarity_threshold=0.7,
        exclude_artigo_id=artigo_id,
    )
    
    if not similar:
        return ""
    
    # Busca resumos dos clusters associados
    parts = []
    seen_clusters = set()
    for item in similar:
        cluster_id = item.get("cluster_id")
        if not cluster_id or cluster_id in seen_clusters:
            continue
        seen_clusters.add(cluster_id)
        
        cluster = db.query(ClusterEvento).filter(
            ClusterEvento.id == cluster_id,
            ClusterEvento.status == 'ativo',
        ).first()
        
        if cluster and cluster.resumo_cluster:
            parts.append(
                f"[Similaridade {item['similarity']:.0%}] ({cluster.prioridade}) {cluster.resumo_cluster[:300]}"
            )
    
    if not parts:
        return ""
    
    return "\n\n".join(parts[:5])


def get_context_for_cluster(
    db: Session,
    cluster_id: int,
    days_graph: int = 7,
    days_vector: int = 30,
) -> str:
    """
    Busca contexto combinado (grafo + vetorial) para um cluster inteiro.
    Usado pelo Expandir e pelo Chat para enriquecer prompts.
    
    1. Busca entidades dos artigos do cluster (via graph_edges)
    2. Busca contexto historico no grafo (ultimos N dias)
    3. Busca artigos semanticamente similares (via embedding_v2)
    4. Combina tudo num texto unico
    """
    parts = []
    
    try:
        # 1. Buscar artigos do cluster
        artigos = (
            db.query(ArtigoBruto)
            .filter(ArtigoBruto.cluster_id == cluster_id)
            .all()
        )
        if not artigos:
            return ""
        
        artigo_ids = [a.id for a in artigos]
        
        # 2. Buscar entidades conectadas ao cluster
        edges = (
            db.query(GraphEdge)
            .filter(GraphEdge.artigo_id.in_(artigo_ids))
            .all()
        )
        
        entity_ids = list(set(e.entity_id for e in edges))
        
        if entity_ids:
            entities = (
                db.query(GraphEntity)
                .filter(GraphEntity.id.in_(entity_ids))
                .all()
            )
            entity_names = [e.canonical_name for e in entities]
            
            # 3. Contexto temporal do grafo
            if entity_names:
                contexto_grafo = get_historical_context_for_entities(
                    db=db,
                    entity_names=entity_names[:5],  # Top 5
                    days=days_graph,
                    max_results=5,
                )
                if contexto_grafo:
                    parts.append(f"=== HISTORICO NO GRAFO (entidades relacionadas, {days_graph} dias) ===\n{contexto_grafo}")
        
        # 4. Busca vetorial (pega embedding do primeiro artigo com embedding_v2)
        artigo_com_emb = next((a for a in artigos if a.embedding_v2 is not None), None)
        if artigo_com_emb:
            contexto_vetorial = get_vector_context_for_article(
                db=db,
                embedding_bytes=artigo_com_emb.embedding_v2,
                artigo_id=artigo_com_emb.id,
                days=days_vector,
                max_results=5,
            )
            if contexto_vetorial:
                parts.append(f"=== ARTIGOS SIMILARES (busca vetorial, {days_vector} dias) ===\n{contexto_vetorial}")
    
    except Exception as e:
        # CRITICO: Rollback para limpar transacao PostgreSQL corrompida
        # Sem isso, qualquer erro SQL aqui envenena o db.commit() posterior
        # em classificar_e_resumir_cluster, causando InFailedSqlTransaction
        try:
            db.rollback()
        except Exception:
            pass
        parts.append(f"[Contexto indisponivel: {str(e)[:100]}]")
    
    return "\n\n".join(parts) if parts else ""


def get_cluster_graph_data(
    db: Session,
    cluster_id: int,
    max_entity_nodes: int = 30,
    max_cluster_nodes: int = 10,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Gera dados do grafo de relacionamentos para visualizacao D3.js.
    
    Retorna nodes (entidades + clusters) e edges para um cluster especifico.
    Profundidade N1: entidades do cluster + clusters que compartilham entidades.
    """
    nodes = []
    edges_list = []
    seen_nodes = set()
    
    # 1. Artigos do cluster central
    artigos = (
        db.query(ArtigoBruto)
        .filter(ArtigoBruto.cluster_id == cluster_id)
        .all()
    )
    if not artigos:
        return {"center_cluster_id": cluster_id, "nodes": [], "edges": [], "stats": {"total_entities": 0, "depth": 0}}
    
    artigo_ids = [a.id for a in artigos]
    
    # Node do cluster central
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    center_label = cluster.titulo_cluster[:60] if cluster and cluster.titulo_cluster else f"Cluster {cluster_id}"
    center_node_id = f"c_{cluster_id}"
    nodes.append({
        "id": center_node_id,
        "label": center_label,
        "type": "cluster",
        "subtype": cluster.prioridade if cluster else "P3",
        "size": len(artigos),
    })
    seen_nodes.add(center_node_id)
    
    # 2. Entidades conectadas ao cluster
    graph_edges = (
        db.query(GraphEdge)
        .filter(GraphEdge.artigo_id.in_(artigo_ids))
        .all()
    )
    
    entity_ids = list(set(e.entity_id for e in graph_edges))
    if not entity_ids:
        return {"center_cluster_id": cluster_id, "nodes": nodes, "edges": [], "stats": {"total_entities": 0, "depth": 0}}
    
    entities = (
        db.query(GraphEntity)
        .filter(GraphEntity.id.in_(entity_ids))
        .all()
    )
    entity_map = {e.id: e for e in entities}
    
    # Conta mencoes por entidade para sizing
    entity_mention_count = {}
    for edge in graph_edges:
        entity_mention_count[edge.entity_id] = entity_mention_count.get(edge.entity_id, 0) + 1
    
    # Adiciona nodes de entidades (limitado)
    sorted_entities = sorted(entity_ids, key=lambda eid: entity_mention_count.get(eid, 0), reverse=True)
    
    for eid in sorted_entities[:max_entity_nodes]:
        ent = entity_map.get(eid)
        if not ent:
            continue
        node_id = f"e_{eid}"
        if node_id not in seen_nodes:
            nodes.append({
                "id": node_id,
                "label": ent.canonical_name,
                "type": "entity",
                "subtype": ent.entity_type,
                "size": entity_mention_count.get(eid, 1),
            })
            seen_nodes.add(node_id)
        
        # Edge entidade -> cluster central
        rel = "MENTIONED"
        for ge in graph_edges:
            if ge.entity_id == eid:
                rel = ge.relation_type
                break
        edges_list.append({
            "source": node_id,
            "target": center_node_id,
            "relation": rel,
            "weight": entity_mention_count.get(eid, 1),
        })
    
    # 3. N1: Outros clusters que compartilham entidades (ultimos N dias)
    cutoff = datetime.utcnow() - timedelta(days=days)
    selected_entity_ids = sorted_entities[:max_entity_nodes]
    
    related_edges = (
        db.query(GraphEdge.entity_id, ArtigoBruto.cluster_id)
        .join(ArtigoBruto, GraphEdge.artigo_id == ArtigoBruto.id)
        .filter(
            GraphEdge.entity_id.in_(selected_entity_ids),
            ArtigoBruto.cluster_id.isnot(None),
            ArtigoBruto.cluster_id != cluster_id,
            ArtigoBruto.created_at >= cutoff,
        )
        .all()
    )
    
    # Agrupa: entity_id -> set(cluster_ids)
    entity_to_clusters = {}
    for eid, cid in related_edges:
        if cid:
            entity_to_clusters.setdefault(eid, set()).add(cid)
    
    # Seleciona clusters mais conectados
    cluster_count = {}
    for eid, cids in entity_to_clusters.items():
        for cid in cids:
            cluster_count[cid] = cluster_count.get(cid, 0) + 1
    
    top_clusters = sorted(cluster_count.keys(), key=lambda c: cluster_count[c], reverse=True)[:max_cluster_nodes]
    
    for cid in top_clusters:
        related_cluster = db.query(ClusterEvento).filter(
            ClusterEvento.id == cid,
            ClusterEvento.status == 'ativo',
        ).first()
        if not related_cluster:
            continue
        
        node_id = f"c_{cid}"
        if node_id not in seen_nodes:
            nodes.append({
                "id": node_id,
                "label": (related_cluster.titulo_cluster or "")[:60],
                "type": "cluster",
                "subtype": related_cluster.prioridade or "P3",
                "size": cluster_count[cid],
            })
            seen_nodes.add(node_id)
        
        # Edges: entidades compartilhadas -> cluster relacionado
        for eid, cids in entity_to_clusters.items():
            if cid in cids:
                ent_node_id = f"e_{eid}"
                if ent_node_id in seen_nodes:
                    edges_list.append({
                        "source": ent_node_id,
                        "target": node_id,
                        "relation": "SHARED",
                        "weight": 1,
                    })
    
    return {
        "center_cluster_id": cluster_id,
        "nodes": nodes,
        "edges": edges_list,
        "stats": {
            "total_entities": len(entity_ids),
            "depth": 1 if top_clusters else 0,
        },
    }


def get_entity_stats(db: Session) -> Dict[str, Any]:
    """Retorna estatisticas do grafo de conhecimento."""
    total_entities = db.query(func.count(GraphEntity.id)).scalar() or 0
    total_edges = db.query(func.count(GraphEdge.id)).scalar() or 0
    
    entities_by_type = dict(
        db.query(
            GraphEntity.entity_type,
            func.count(GraphEntity.id)
        )
        .group_by(GraphEntity.entity_type)
        .all()
    )
    
    edges_by_relation = dict(
        db.query(
            GraphEdge.relation_type,
            func.count(GraphEdge.id)
        )
        .group_by(GraphEdge.relation_type)
        .all()
    )
    
    return {
        "total_entities": total_entities,
        "total_edges": total_edges,
        "entities_by_type": entities_by_type,
        "edges_by_relation": edges_by_relation,
    }
