"""
Operações CRUD (Create, Read, Update, Delete) para o BTG AlphaFeed.
Funções para interagir com o banco de dados PostgreSQL.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func, text

try:
    from .database import ArtigoBruto, ClusterEvento, SinteseExecutiva, LogProcessamento, ConfiguracaoColeta, EstagiarioChatSession, EstagiarioChatMessage, PromptTag, PromptPrioridadeItem, PromptTemplate
    from .models import ArtigoBrutoCreate, ClusterEventoCreate
    from .utils import get_date_brasil
except ImportError:
    # Fallback para import absoluto quando executado fora do pacote
    from backend.database import ArtigoBruto, ClusterEvento, SinteseExecutiva, LogProcessamento, ConfiguracaoColeta, EstagiarioChatSession, EstagiarioChatMessage, PromptTag, PromptPrioridadeItem, PromptTemplate
    from backend.models import ArtigoBrutoCreate, ClusterEventoCreate
    from backend.utils import get_date_brasil


# ==============================================================================
# OPERAÇÕES CRUD - ARTIGOS BRUTOS
# ==============================================================================

def get_artigo_by_hash(db: Session, hash_unico: str) -> Optional[ArtigoBruto]:
    """Busca um artigo pelo hash único."""
    return db.query(ArtigoBruto).filter(ArtigoBruto.hash_unico == hash_unico).first()


def get_artigo_by_id(db: Session, id_artigo: int) -> Optional[ArtigoBruto]:
    """Busca um artigo pelo ID."""
    return db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()


def create_artigo_bruto(db: Session, artigo_data: ArtigoBrutoCreate) -> ArtigoBruto:
    """Cria um novo artigo bruto no banco."""
    db_artigo = ArtigoBruto(
        hash_unico=artigo_data.hash_unico,
        texto_bruto=artigo_data.texto_bruto,
        url_original=artigo_data.url_original,
        fonte_coleta=artigo_data.fonte_coleta,
        metadados=artigo_data.metadados
    )
    db.add(db_artigo)
    db.commit()
    db.refresh(db_artigo)
    return db_artigo


def update_artigo_processado(
    db: Session, 
    id_artigo: int, 
    dados_processados: Dict[str, Any],
    embedding: Optional[bytes] = None
) -> bool:
    """Atualiza um artigo com os dados processados."""
    def _truncate(value: Optional[str], max_len: int) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value)
        return value_str[:max_len]
    artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
    if not artigo:
        return False
    
    # Atualiza campos processados
    artigo.titulo_extraido = _truncate(dados_processados.get('titulo'), 500)
    artigo.texto_processado = dados_processados.get('texto_completo')
    artigo.jornal = _truncate(dados_processados.get('jornal'), 100)
    artigo.autor = _truncate(dados_processados.get('autor'), 200)
    artigo.pagina = _truncate(dados_processados.get('pagina'), 50)
    
    # Converte data se presente
    if dados_processados.get('data'):
        try:
            artigo.data_publicacao = datetime.fromisoformat(dados_processados['data'])
        except:
            pass
    
    artigo.categoria = _truncate(dados_processados.get('categoria'), 100)
    artigo.tag = _truncate(dados_processados.get('tag'), 50)
    artigo.prioridade = dados_processados.get('prioridade')
    artigo.relevance_score = dados_processados.get('relevance_score')
    artigo.relevance_reason = dados_processados.get('relevance_reason')
    
    if embedding:
        artigo.embedding = embedding
    
    artigo.processed_at = datetime.utcnow()
    artigo.status = 'processado'
    
    db.commit()
    return True

def update_artigo_dados_sem_status(
    db: Session, 
    id_artigo: int, 
    dados_processados: Dict[str, Any],
    embedding: Optional[bytes] = None
) -> bool:
    """Atualiza um artigo com os dados processados SEM alterar o status."""
    def _truncate(value: Optional[str], max_len: int) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value)
        return value_str[:max_len]
    artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
    if not artigo:
        return False
    
    # Atualiza campos processados
    artigo.titulo_extraido = _truncate(dados_processados.get('titulo'), 500)
    artigo.texto_processado = dados_processados.get('texto_completo')
    artigo.jornal = _truncate(dados_processados.get('jornal'), 100)
    artigo.autor = _truncate(dados_processados.get('autor'), 200)
    artigo.pagina = _truncate(dados_processados.get('pagina'), 50)
    
    # Converte data se presente
    if dados_processados.get('data'):
        try:
            artigo.data_publicacao = datetime.fromisoformat(dados_processados['data'])
        except:
            pass
    
    artigo.categoria = _truncate(dados_processados.get('categoria'), 100)
    artigo.tag = _truncate(dados_processados.get('tag'), 50)
    artigo.prioridade = dados_processados.get('prioridade')
    artigo.relevance_score = dados_processados.get('relevance_score')
    artigo.relevance_reason = dados_processados.get('relevance_reason')
    
    # IMPORTANTE: Preserva o tipo_fonte que foi definido durante o carregamento
    # NÃO sobrescreve o tipo_fonte com dados_processados.get('tipo_fonte')
    # CORREÇÃO: Se o artigo não tem tipo_fonte definido, usa o valor dos dados processados
    if not hasattr(artigo, 'tipo_fonte') or artigo.tipo_fonte is None:
        tipo_fonte_dados = dados_processados.get('tipo_fonte')
        if tipo_fonte_dados and tipo_fonte_dados in ('nacional', 'internacional'):
            artigo.tipo_fonte = tipo_fonte_dados
            print(f"    🔍 DEBUG: Artigo {id_artigo} recebe tipo_fonte='{tipo_fonte_dados}' dos dados processados")
    
    if embedding:
        artigo.embedding = embedding
    
    # NÃO altera o status - mantém como está
    # NÃO altera processed_at - será alterado quando realmente processado
    
    db.commit()
    return True


def update_artigo_status(db: Session, id_artigo: int, status: str) -> bool:
    """Atualiza apenas o status de um artigo."""
    artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
    if not artigo:
        return False
    
    artigo.status = status
    if status in ['processado', 'irrelevante', 'erro']:
        artigo.processed_at = datetime.utcnow()
    
    db.commit()
    return True


def get_artigos_pendentes(db: Session, limite: int = 100, day_str: Optional[str] = None) -> List[ArtigoBruto]:
    """Busca artigos com status 'pendente' para processamento."""
    query = db.query(ArtigoBruto).filter(ArtigoBruto.status == 'pendente')
    
    # Se uma data específica for fornecida, filtra por ela
    if day_str:
        query = query.filter(func.date(ArtigoBruto.created_at) == day_str)
    
    return query.order_by(ArtigoBruto.created_at.asc()).limit(limite).all()


def get_artigos_by_cluster(db: Session, cluster_id: int) -> List[ArtigoBruto]:
    """Busca todos os artigos de um cluster específico."""
    return db.query(ArtigoBruto).filter(
        ArtigoBruto.cluster_id == cluster_id
    ).all()


def get_textos_brutos_por_cluster_id(db: Session, cluster_id: int) -> List[Dict[str, Any]]:
    """
    Busca os textos brutos originais e metadados essenciais de todos os artigos
    associados a um determinado ID de cluster. Não retorna resumos processados.
    """
    artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == cluster_id).all()
    if not artigos:
        return []
    textos_brutos: List[Dict[str, Any]] = []
    for artigo in artigos:
        textos_brutos.append({
            "id": artigo.id,
            "titulo": (artigo.titulo_extraido or "Sem título"),
            "fonte": (artigo.jornal or "Fonte desconhecida"),
            "texto_bruto": (artigo.texto_bruto or artigo.texto_processado or "")
        })
    return textos_brutos


# ==============================================================================
# OPERAÇÕES CRUD - CLUSTERS DE EVENTOS
# ==============================================================================

def get_active_clusters_today(db: Session) -> List[ClusterEvento]:
    """Busca clusters ativos criados hoje para clusterização."""
    hoje = datetime.utcnow().date()
    return db.query(ClusterEvento).filter(
        ClusterEvento.status == 'ativo',
        func.date(ClusterEvento.created_at) == hoje
    ).all()


def get_cluster_by_id(db: Session, cluster_id: int) -> Optional[ClusterEvento]:
    """Busca um cluster pelo ID."""
    return db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()


def create_cluster(db: Session, cluster_data: ClusterEventoCreate) -> ClusterEvento:
    """Cria um novo cluster de eventos."""
    # Truncamento defensivo para respeitar limites do schema
    def _truncate(value: Optional[str], max_len: int) -> Optional[str]:
        if value is None:
            return None
        value_str = str(value)
        return value_str[:max_len]

    # Verifica se já existe um cluster com o mesmo título e tag hoje
    hoje = datetime.utcnow().date()
    cluster_existente = db.query(ClusterEvento).filter(
        ClusterEvento.titulo_cluster == _truncate(cluster_data.titulo_cluster, 500),
        ClusterEvento.tag == _truncate(cluster_data.tag, 50),
        ClusterEvento.status == 'ativo',
        func.date(ClusterEvento.created_at) == hoje
    ).first()
    
    if cluster_existente:
        print(f"⚠️ Cluster já existe: {cluster_existente.id} - '{cluster_data.titulo_cluster}'")
        return cluster_existente
    
    # Cria novo cluster
    # Normaliza prioridade inválida/None para evitar NOT NULL violations
    from .utils import corrigir_prioridade_invalida

    prioridade_normalizada = corrigir_prioridade_invalida(cluster_data.prioridade if cluster_data.prioridade else None)

    # Normaliza tipo_fonte
    tipo_fonte_normalizado = None
    try:
        tf = getattr(cluster_data, 'tipo_fonte', None)
        if isinstance(tf, str):
            tf = tf.strip().lower()
            if tf in ('nacional', 'internacional'):
                tipo_fonte_normalizado = tf
    except Exception:
        pass

    db_cluster = ClusterEvento(
        titulo_cluster=_truncate(cluster_data.titulo_cluster, 500),
        resumo_cluster=cluster_data.resumo_cluster,
        tag=_truncate(cluster_data.tag, 50),
        prioridade=_truncate(prioridade_normalizada, 20),
        embedding_medio=cluster_data.embedding_medio,
        tipo_fonte=tipo_fonte_normalizado or 'nacional'
    )
    db.add(db_cluster)
    db.commit()
    db.refresh(db_cluster)
    return db_cluster


def associate_artigo_to_cluster(db: Session, id_artigo: int, id_cluster: int) -> bool:
    """Associa um artigo a um cluster e atualiza métricas."""
    artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == id_cluster).first()
    
    if not artigo or not cluster:
        return False
    
    # Verifica se o artigo já está associado a este cluster
    if artigo.cluster_id == id_cluster:
        return True

    # Verifica se o artigo está associado a outro cluster
    if artigo.cluster_id:
        # Remove associação anterior silenciosamente
        pass
        # Remove associação anterior
        cluster_anterior = db.query(ClusterEvento).filter(ClusterEvento.id == artigo.cluster_id).first()
        if cluster_anterior:
            cluster_anterior.total_artigos = max(0, cluster_anterior.total_artigos - 1)
    
    # CORREÇÃO: Verifica compatibilidade de tipo_fonte entre artigo e cluster
    tipo_fonte_artigo = getattr(artigo, 'tipo_fonte', 'nacional')
    tipo_fonte_cluster = getattr(cluster, 'tipo_fonte', 'nacional')
    
    if tipo_fonte_artigo != tipo_fonte_cluster:
        print(f"⚠️ AVISO: Incompatibilidade de tipo_fonte - artigo={tipo_fonte_artigo}, cluster={tipo_fonte_cluster}")
        # Não impede a associação, mas registra o aviso
    
    # Associa o artigo ao cluster
    artigo.cluster_id = id_cluster
    
    # Atualiza métricas do cluster
    cluster.total_artigos += 1
    cluster.ultima_atualizacao = datetime.utcnow()
    cluster.updated_at = datetime.utcnow()
    
    # Atualiza a prioridade do cluster se necessário (menor valor = maior prioridade)
    prioridades = {'P1_CRITICO': 1, 'P2_ESTRATEGICO': 2, 'P3_MONITORAMENTO': 3}
    if prioridades.get(artigo.prioridade, 3) < prioridades.get(cluster.prioridade, 3):
        cluster.prioridade = artigo.prioridade
    
    db.commit()
    return True


def update_cluster_embedding(db: Session, id_cluster: int, embedding_medio: bytes) -> bool:
    """Atualiza o embedding médio de um cluster."""
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == id_cluster).first()
    if not cluster:
        return False
    
    cluster.embedding_medio = embedding_medio
    cluster.updated_at = datetime.utcnow()
    db.commit()
    return True


def get_clusters_for_feed(db: Session, data_inicio: Optional[datetime] = None) -> List[Dict]:
    """
    Busca clusters ativos para exibição no feed.
    Retorna dados formatados para a API.
    """
    if not data_inicio:
        # Por padrão, busca clusters dos últimos 3 dias
        data_inicio = datetime.utcnow() - timedelta(days=3)
    
    clusters = db.query(ClusterEvento).filter(
        ClusterEvento.status == 'ativo',
        ClusterEvento.created_at >= data_inicio
    ).order_by(
        # Ordena por prioridade (P1 primeiro) e depois por data
        text("CASE WHEN prioridade = 'P1_CRITICO' THEN 1 WHEN prioridade = 'P2_ESTRATEGICO' THEN 2 ELSE 3 END"),
        ClusterEvento.updated_at.desc()
    ).all()
    
    feed_data = []
    for cluster in clusters:
        # Busca artigos do cluster para contar fontes
        artigos = get_artigos_by_cluster(db, cluster.id)
        
        # Formata dados para o frontend
        cluster_data = {
            "id": cluster.id,
            "titulo_final": cluster.titulo_cluster,
            "resumo_final": cluster.resumo_cluster or "Resumo em processamento...",
            "prioridade": cluster.prioridade,
            "tags": [cluster.tag],
            "fontes": [
                {
                    "nome": artigo.jornal or "Fonte Desconhecida",
                    "tipo": "web" if artigo.url_original else "pdf",
                    "url": artigo.url_original
                }
                for artigo in artigos[:5]  # Limita a 5 fontes por cluster
            ],
            "timestamp": _format_relative_time(cluster.updated_at)
        }
        feed_data.append(cluster_data)
    
    return feed_data


# ==============================================================================
# OPERAÇÕES CRUD - SÍNTESE EXECUTIVA
# ==============================================================================

def get_sintese_today(db: Session) -> Optional[SinteseExecutiva]:
    """Busca a síntese executiva do dia atual."""
    hoje = datetime.utcnow().date()
    return db.query(SinteseExecutiva).filter(
        func.date(SinteseExecutiva.data_sintese) == hoje
    ).first()


def create_or_update_sintese(db: Session, texto_sintese: str, metricas: Dict[str, int]) -> SinteseExecutiva:
    """Cria ou atualiza a síntese executiva do dia."""
    hoje = datetime.utcnow().date()
    sintese_existente = get_sintese_today(db)
    
    if sintese_existente:
        # Atualiza síntese existente
        sintese_existente.texto_sintese = texto_sintese
        sintese_existente.total_noticias_coletadas = metricas.get('coletadas', 0)
        sintese_existente.total_eventos_unicos = metricas.get('eventos', 0)
        sintese_existente.total_analises_criticas = metricas.get('p1', 0)
        sintese_existente.total_monitoramento = metricas.get('p2p3', 0)
        sintese_existente.updated_at = datetime.utcnow()
        db.commit()
        return sintese_existente
    else:
        # Cria nova síntese
        nova_sintese = SinteseExecutiva(
            data_sintese=datetime.utcnow(),
            texto_sintese=texto_sintese,
            total_noticias_coletadas=metricas.get('coletadas', 0),
            total_eventos_unicos=metricas.get('eventos', 0),
            total_analises_criticas=metricas.get('p1', 0),
            total_monitoramento=metricas.get('p2p3', 0)
        )
        db.add(nova_sintese)
        db.commit()
        db.refresh(nova_sintese)
        return nova_sintese


# ==============================================================================
# OPERAÇÕES CRUD - MÉTRICAS E ESTATÍSTICAS
# ==============================================================================

def get_metricas_today(db: Session) -> Dict[str, int]:
    """
    Busca métricas do dia atual.
    Retorna estatísticas de artigos coletados, eventos únicos, etc.
    """
    hoje = get_date_brasil()
    
    # Artigos coletados hoje
    artigos_coletados = db.query(ArtigoBruto).filter(
        func.date(ArtigoBruto.created_at) == hoje
    ).count()
    
    # Clusters ativos hoje
    clusters_ativos = db.query(ClusterEvento).filter(
        func.date(ClusterEvento.created_at) == hoje,
        ClusterEvento.status == 'ativo'
    ).count()
    
    # Fontes diferentes hoje (count distinct)
    fontes_diferentes = db.query(ArtigoBruto.jornal).filter(
        func.date(ArtigoBruto.created_at) == hoje,
        ArtigoBruto.jornal.isnot(None)
    ).distinct().count()
    
    return {
        "coletadas": artigos_coletados,
        "eventos": clusters_ativos,
        "fontes": fontes_diferentes
    }


def get_metricas_by_date(db: Session, target_date: datetime.date) -> Dict[str, int]:
    """
    Busca métricas de uma data específica (otimizada com índices).
    """
    # Artigos coletados na data (usando índice)
    artigos_coletados = db.query(ArtigoBruto).filter(
        func.date(ArtigoBruto.created_at) == target_date
    ).count()
    
    # Clusters criados na data específica (usando índices compostos) - exclui IRRELEVANTE
    clusters_ativos = db.query(ClusterEvento).filter(
        func.date(ClusterEvento.created_at) == target_date,
        ClusterEvento.status == 'ativo',
        ClusterEvento.prioridade != 'IRRELEVANTE'
    ).count()
    
    # Fontes diferentes na data específica (count distinct)
    fontes_diferentes = db.query(ArtigoBruto.jornal).filter(
        func.date(ArtigoBruto.created_at) == target_date,
        ArtigoBruto.jornal.isnot(None)
    ).distinct().count()
    
    # Total de clusters exibíveis no front (exclui IRRELEVANTE)
    clusters_exibiveis = db.query(ClusterEvento).filter(
        func.date(ClusterEvento.created_at) == target_date,
        ClusterEvento.status == 'ativo',
        ClusterEvento.prioridade != 'IRRELEVANTE',
        ClusterEvento.tag != 'IRRELEVANTE'
    ).count()
    
    return {
        "coletadas": artigos_coletados,
        "eventos": clusters_ativos,
        "fontes": fontes_diferentes,
        # Por solicitação, este campo representa a quantidade de itens exibidos no front
        "com_resumo": clusters_exibiveis
    }

# ===================== FEEDBACK =====================
def create_feedback(db: Session, artigo_id: int, feedback: str) -> int:
    try:
        from .database import FeedbackNoticia
    except ImportError:
        from backend.database import FeedbackNoticia
    novo = FeedbackNoticia(artigo_id=artigo_id, feedback=feedback, processed=False)
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo.id


def list_feedback(db: Session, processed: Optional[bool] = None, limit: int = 100):
    try:
        from .database import FeedbackNoticia
    except ImportError:
        from backend.database import FeedbackNoticia
    q = db.query(FeedbackNoticia).order_by(FeedbackNoticia.created_at.desc())
    if processed is not None:
        q = q.filter(FeedbackNoticia.processed == processed)
    return q.limit(limit).all()


def mark_feedback_processed(db: Session, feedback_id: int) -> bool:
    try:
        from .database import FeedbackNoticia
    except ImportError:
        from backend.database import FeedbackNoticia
    fb = db.query(FeedbackNoticia).filter(FeedbackNoticia.id == feedback_id).first()
    if not fb:
        return False
    fb.processed = True
    db.commit()
    return True


# ===================== AGREGADOS (BI) =====================
def agg_noticias_por_dia(db: Session, dias: int = 30):
    base_date = datetime.utcnow() - timedelta(days=dias)
    q = db.query(
        func.date(ArtigoBruto.created_at).label('dia'),
        func.count(ArtigoBruto.id).label('num_artigos'),
    ).filter(ArtigoBruto.created_at >= base_date).group_by(func.date(ArtigoBruto.created_at)).order_by(func.date(ArtigoBruto.created_at))
    artigos = q.all()
    # clusters por dia
    from .database import ClusterEvento as _Cluster
    qc = db.query(
        func.date(_Cluster.created_at).label('dia'),
        func.count(_Cluster.id).label('num_clusters'),
    ).filter(_Cluster.created_at >= base_date).group_by(func.date(_Cluster.created_at)).order_by(func.date(_Cluster.created_at)).all()
    clusters_map = {row.dia: row.num_clusters for row in qc}
    return [
        {"dia": str(row.dia), "num_artigos": row.num_artigos, "num_clusters": clusters_map.get(row.dia, 0)}
        for row in artigos
    ]


def agg_noticias_por_fonte(db: Session, limit: int = 20):
    q = db.query(ArtigoBruto.jornal, func.count(ArtigoBruto.id).label('qtd')).group_by(ArtigoBruto.jornal).order_by(func.count(ArtigoBruto.id).desc()).limit(limit)
    return [{"jornal": j or "Desconhecido", "qtd": qtd} for j, qtd in q.all()]


def agg_noticias_por_autor(db: Session, limit: int = 20):
    q = db.query(ArtigoBruto.autor, func.count(ArtigoBruto.id).label('qtd')).group_by(ArtigoBruto.autor).order_by(func.count(ArtigoBruto.id).desc()).limit(limit)
    return [{"autor": a or "N/A", "qtd": qtd} for a, qtd in q.all()]


def agg_estatisticas_gerais(db: Session):
    """
    Retorna estatísticas gerais do sistema
    """
    # Total de artigos
    total_artigos = db.query(func.count(ArtigoBruto.id)).scalar() or 0
    
    # Total de clusters
    from .database import ClusterEvento as _Cluster
    total_clusters = db.query(func.count(_Cluster.id)).scalar() or 0
    
    # Dias diferentes com notícias
    dias_diferentes = db.query(func.count(func.distinct(func.date(ArtigoBruto.created_at)))).scalar() or 0
    
    # Contagem por tipo_fonte
    try:
        total_artigos_nacional = db.query(func.count(ArtigoBruto.id)).filter(ArtigoBruto.tipo_fonte == 'nacional').scalar() or 0
        total_artigos_internacional = db.query(func.count(ArtigoBruto.id)).filter(ArtigoBruto.tipo_fonte == 'internacional').scalar() or 0
    except Exception:
        total_artigos_nacional = 0
        total_artigos_internacional = 0

    try:
        from .database import ClusterEvento as _Cluster
        total_clusters_nacional = db.query(func.count(_Cluster.id)).filter(_Cluster.tipo_fonte == 'nacional').scalar() or 0
        total_clusters_internacional = db.query(func.count(_Cluster.id)).filter(_Cluster.tipo_fonte == 'internacional').scalar() or 0
    except Exception:
        total_clusters_nacional = 0
        total_clusters_internacional = 0

    return {
        "total_artigos": total_artigos,
        "total_clusters": total_clusters,
        "dias_diferentes": dias_diferentes,
        "artigos_nacional": total_artigos_nacional,
        "artigos_internacional": total_artigos_internacional,
        "clusters_nacional": total_clusters_nacional,
        "clusters_internacional": total_clusters_internacional
    }


def agg_noticias_por_tag(db: Session, limit: int = 10):
    """
    Retorna contagem de notícias por tag, agrupando as menores como "Outros"
    Usa dados da tabela ClusterEvento (processados) em vez de ArtigoBruto (brutos)
    """
    # Busca todas as tags com contagem dos clusters processados
    q = db.query(ClusterEvento.tag, func.count(ClusterEvento.id).label('qtd')).filter(
        ClusterEvento.tag.isnot(None),
        ClusterEvento.tag != '',
        ClusterEvento.tag != 'IRRELEVANTE',
        ClusterEvento.status == 'ativo'
    ).group_by(ClusterEvento.tag).order_by(func.count(ClusterEvento.id).desc()).all()
    
    if not q:
        return []
    
    # Separa as top tags e agrupa o resto
    top_tags = q[:limit]
    outras_tags = q[limit:]
    
    # Calcula total das outras tags
    total_outras = sum(item.qtd for item in outras_tags) if outras_tags else 0
    
    resultado = [{"tag": item.tag, "qtd": item.qtd} for item in top_tags]
    
    # Adiciona "Outros" se houver outras tags
    if total_outras > 0:
        resultado.append({"tag": "Outros", "qtd": total_outras})
    
    return resultado


def agg_noticias_por_prioridade(db: Session):
    """
    Retorna contagem de notícias por prioridade
    Usa dados da tabela ClusterEvento (processados) em vez de ArtigoBruto (brutos)
    """
    q = db.query(ClusterEvento.prioridade, func.count(ClusterEvento.id).label('qtd')).filter(
        ClusterEvento.prioridade.isnot(None),
        ClusterEvento.prioridade != '',
        ClusterEvento.prioridade != 'IRRELEVANTE',
        ClusterEvento.status == 'ativo'
    ).group_by(ClusterEvento.prioridade).order_by(func.count(ClusterEvento.id).desc()).all()
    
    return [{"prioridade": item.prioridade or "Sem Prioridade", "qtd": item.qtd} for item in q]


def get_sintese_by_date(db: Session, target_date: datetime.date) -> Optional[SinteseExecutiva]:
    """
    Busca síntese executiva de uma data específica.
    """
    return db.query(SinteseExecutiva).filter(
        func.date(SinteseExecutiva.data_sintese) == target_date
    ).first()


def get_clusters_for_feed_by_date(db: Session, target_date: datetime.date, page: int = 1, page_size: int = 20, load_full_text: bool = False, priority: Optional[str] = None, tipo_fonte: Optional[str] = None) -> Dict[str, Any]:
    """
    Busca clusters para o feed de uma data específica com paginação e carregamento lazy.
    Retorna lista formatada para o frontend com opção de carregar texto completo sob demanda.
    
    Args:
        db: Sessão do banco de dados
        target_date: Data para filtrar
        page: Número da página (começa em 1)
        page_size: Tamanho da página
        load_full_text: Se True, carrega texto completo. Se False, apenas título e resumo
        priority: Filtro opcional por prioridade (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO)
    """
    # Calcula offset para paginação
    offset = (page - 1) * page_size
    
    # Busca clusters criados na data específica com paginação (exclui IRRELEVANTE)
    clusters_query = db.query(ClusterEvento).filter(
        func.date(ClusterEvento.created_at) == target_date,
        ClusterEvento.status == 'ativo',
        ClusterEvento.prioridade != 'IRRELEVANTE',
        ClusterEvento.tag != 'IRRELEVANTE'
    )
    
    # Aplica filtro de prioridade se especificado
    if priority:
        clusters_query = clusters_query.filter(ClusterEvento.prioridade == priority)
    
    # Aplica filtro de tipo de fonte se especificado
    # Compatibilidade:
    # - 'internacional' → apenas internacional
    # - 'nacional' → nacional legado + brasil_fisico + brasil_online
    # - 'brasil_fisico' → apenas brasil_fisico
    # - 'brasil_online' → apenas brasil_online (não agrega legado)
    if tipo_fonte:
        if tipo_fonte == 'internacional':
            clusters_query = clusters_query.filter(ClusterEvento.tipo_fonte == 'internacional')
        elif tipo_fonte == 'nacional':
            # Compat: inclui legado 'nacional' e os novos físicos/online
            clusters_query = clusters_query.filter(ClusterEvento.tipo_fonte.in_(['nacional', 'brasil_fisico', 'brasil_online']))
        elif tipo_fonte == 'brasil_fisico':
            clusters_query = clusters_query.filter(ClusterEvento.tipo_fonte == 'brasil_fisico')
        elif tipo_fonte == 'brasil_online':
            clusters_query = clusters_query.filter(ClusterEvento.tipo_fonte == 'brasil_online')
    
    # Ordena por prioridade (P1 primeiro) e depois por data
    clusters_query = clusters_query.order_by(
        text("CASE WHEN prioridade = 'P1_CRITICO' THEN 1 WHEN prioridade = 'P2_ESTRATEGICO' THEN 2 ELSE 3 END"),
        ClusterEvento.created_at.desc()
    )
    
    # Conta total de clusters para paginação
    total_clusters = clusters_query.count()
    
    # Aplica paginação
    clusters = clusters_query.offset(offset).limit(page_size).all()
    
    resultado = []
    
    for cluster in clusters:
        # Busca todos os artigos do cluster
        artigos = db.query(ArtigoBruto).filter(
            ArtigoBruto.cluster_id == cluster.id
        ).all()
        
        # Formata fontes para o frontend (sempre carrega)
        fontes = []
        for artigo in artigos:
            fonte = {
                "nome": artigo.jornal or "Fonte Desconhecida",
                "tipo": "web" if artigo.url_original else "pdf",
                "url": artigo.url_original,
                "autor": artigo.autor or "N/A",
                "pagina": artigo.pagina
            }
            fontes.append(fonte)
        
        # Formata tags
        tags = [cluster.tag] if cluster.tag else []
        
        # Calcula feedback agregado do cluster (likes/dislikes e último feedback)
        try:
            try:
                from .database import FeedbackNoticia as _Feedback
            except ImportError:
                from backend.database import FeedbackNoticia as _Feedback

            likes = db.query(func.count(_Feedback.id)).join(
                ArtigoBruto, _Feedback.artigo_id == ArtigoBruto.id
            ).filter(
                ArtigoBruto.cluster_id == cluster.id,
                _Feedback.feedback == 'like'
            ).scalar() or 0

            dislikes = db.query(func.count(_Feedback.id)).join(
                ArtigoBruto, _Feedback.artigo_id == ArtigoBruto.id
            ).filter(
                ArtigoBruto.cluster_id == cluster.id,
                _Feedback.feedback == 'dislike'
            ).scalar() or 0

            ultimo = db.query(_Feedback).join(
                ArtigoBruto, _Feedback.artigo_id == ArtigoBruto.id
            ).filter(
                ArtigoBruto.cluster_id == cluster.id
            ).order_by(_Feedback.created_at.desc()).first()

            feedback_info = {
                "likes": int(likes),
                "dislikes": int(dislikes),
                "last": (ultimo.feedback if ultimo else None)
            }
        except Exception:
            feedback_info = {"likes": 0, "dislikes": 0, "last": None}

        # Cria item do feed
        item = {
            "id": cluster.id,
            "titulo_final": cluster.titulo_cluster,
            "resumo_final": cluster.resumo_cluster or "Resumo em processamento...",
            "prioridade": cluster.prioridade,
            "tag": cluster.tag,
            "tags": tags,
            "fontes": fontes,
            "timestamp": _format_relative_time(cluster.updated_at),
            "total_artigos": len(artigos),
            "created_at": cluster.created_at.isoformat(),
            "feedback": feedback_info
        }
        
        # Carrega texto completo apenas se solicitado
        if load_full_text:
            item["texto_completo"] = cluster.resumo_cluster or ""
            item["artigos_detalhados"] = []
            for artigo in artigos:
                item["artigos_detalhados"].append({
                    "id": artigo.id,
                    "titulo": artigo.titulo_extraido,
                    "texto": artigo.texto_processado,
                    "jornal": artigo.jornal,
                    "autor": artigo.autor,
                    "data": artigo.data_publicacao.isoformat() if artigo.data_publicacao else None
                })
        
        resultado.append(item)
    
    return {
        "clusters": resultado,
        "paginacao": {
            "pagina_atual": page,
            "tamanho_pagina": page_size,
            "total_clusters": total_clusters,
            "total_paginas": (total_clusters + page_size - 1) // page_size,
            "tem_proxima": page * page_size < total_clusters,
            "tem_anterior": page > 1
        }
    }


# ===================== CRUD Estagiário =====================
def create_estagiario_session(db: Session, data_referencia: datetime.date) -> int:
    s = EstagiarioChatSession(data_referencia=datetime.combine(data_referencia, datetime.min.time()))
    db.add(s)
    db.commit()
    db.refresh(s)
    return s.id


def add_estagiario_message(db: Session, session_id: int, role: str, content: str) -> int:
    m = EstagiarioChatMessage(session_id=session_id, role=role, content=content)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m.id


def list_estagiario_messages(db: Session, session_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    q = db.query(EstagiarioChatMessage).filter(EstagiarioChatMessage.session_id == session_id).order_by(EstagiarioChatMessage.timestamp.asc())
    return [
        {"id": msg.id, "role": msg.role, "content": msg.content, "timestamp": msg.timestamp.isoformat()}
        for msg in q.limit(limit).all()
    ]


def get_cluster_details_by_id(db: Session, cluster_id: int) -> Optional[Dict[str, Any]]:
    """
    Busca detalhes completos de um cluster específico.
    Usado para carregamento lazy quando o usuário clica em uma notícia.
    """
    cluster = db.query(ClusterEvento).filter(
        ClusterEvento.id == cluster_id,
        ClusterEvento.status == 'ativo'
    ).first()
    
    if not cluster:
        return None
    
    # Busca todos os artigos do cluster
    artigos = db.query(ArtigoBruto).filter(
        ArtigoBruto.cluster_id == cluster_id
    ).order_by(ArtigoBruto.created_at.desc()).all()
    
    # Formata artigos detalhados
    artigos_detalhados = []
    for artigo in artigos:
        artigos_detalhados.append({
            "id": artigo.id,
            "titulo": artigo.titulo_extraido,
            "texto_completo": artigo.texto_processado,
            "jornal": artigo.jornal,
            "autor": artigo.autor,
            "data_publicacao": artigo.data_publicacao.isoformat() if artigo.data_publicacao else None,
            "categoria": artigo.categoria,
            "tag": artigo.tag,
            "prioridade": artigo.prioridade,
            "relevance_score": artigo.relevance_score,
            "relevance_reason": artigo.relevance_reason,
            "url_original": artigo.url_original,
            "created_at": artigo.created_at.isoformat()
        })
    
    # Formata fontes para o frontend
    fontes = []
    for artigo in artigos:
        fonte = {
            "nome": artigo.jornal or "Fonte Desconhecida",
            "tipo": "web" if artigo.url_original else "pdf",
            "url": artigo.url_original,
            "autor": artigo.autor or "N/A",
            "pagina": artigo.pagina,
            "titulo_original": artigo.titulo_extraido or "Título não disponível"
        }
        fontes.append(fonte)
    
    return {
        "id": cluster.id,
        "titulo_final": cluster.titulo_cluster,
        "resumo_final": cluster.resumo_cluster,
        "tag": cluster.tag,
        "prioridade": cluster.prioridade,
        "created_at": cluster.created_at.isoformat(),
        "updated_at": cluster.updated_at.isoformat(),
        "total_artigos": len(artigos),
        "fontes": fontes,
        "artigos": artigos_detalhados
    }


# ==============================================================================
# OPERAÇÕES CRUD - LOGS
# ==============================================================================

def create_log(
    db: Session, 
    nivel: str, 
    componente: str, 
    mensagem: str, 
    detalhes: Optional[Dict] = None,
    artigo_id: Optional[int] = None,
    cluster_id: Optional[int] = None
) -> LogProcessamento:
    """Cria um novo log de processamento."""
    log = LogProcessamento(
        nivel=nivel,
        componente=componente,
        mensagem=mensagem,
        detalhes=detalhes or {},
        artigo_id=artigo_id,
        cluster_id=cluster_id
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def _format_relative_time(timestamp: datetime) -> str:
    """Formata um timestamp em tempo relativo (há X minutos/horas)."""
    agora = datetime.utcnow()
    diferenca = agora - timestamp
    
    if diferenca.days > 0:
        return f"há {diferenca.days} dias"
    elif diferenca.seconds >= 3600:
        horas = diferenca.seconds // 3600
        return f"há {horas} horas"
    elif diferenca.seconds >= 60:
        minutos = diferenca.seconds // 60
        return f"há {minutos} minutos"
    else:
        return "há poucos segundos"


def get_database_stats(db: Session) -> Dict[str, Any]:
    """Retorna estatísticas gerais do banco de dados."""
    try:
        # Contagem de artigos por status
        artigos_por_status = db.query(
            ArtigoBruto.status,
            func.count(ArtigoBruto.id).label('count')
        ).group_by(ArtigoBruto.status).all()
        
        # Contagem de clusters por prioridade
        clusters_por_prioridade = db.query(
            ClusterEvento.prioridade,
            func.count(ClusterEvento.id).label('count')
        ).group_by(ClusterEvento.prioridade).all()
        
        # Contagem de clusters por tag
        clusters_por_tag = db.query(
            ClusterEvento.tag,
            func.count(ClusterEvento.id).label('count')
        ).group_by(ClusterEvento.tag).all()
        
        # Estatísticas de tempo
        artigos_hoje = db.query(ArtigoBruto).filter(
            func.date(ArtigoBruto.created_at) == datetime.utcnow().date()
        ).count()
        
        clusters_hoje = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == datetime.utcnow().date()
        ).count()
        
        return {
            'artigos_por_status': {status: count for status, count in artigos_por_status},
            'clusters_por_prioridade': {prioridade: count for prioridade, count in clusters_por_prioridade},
            'clusters_por_tag': {tag: count for tag, count in clusters_por_tag},
            'artigos_hoje': artigos_hoje,
            'clusters_hoje': clusters_hoje,
            'total_artigos': db.query(ArtigoBruto).count(),
            'total_clusters': db.query(ClusterEvento).count(),
            'total_sinteses': db.query(SinteseExecutiva).count(),
            'total_prompt_tags': db.query(PromptTag).count(),
            'total_prompt_prioridade_itens': db.query(PromptPrioridadeItem).count(),
            'total_prompt_templates': db.query(PromptTemplate).count(),
        }
    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")
        return {}


# ==============================================================================
# OPERAÇÕES CRUD - CHAT E ALTERAÇÕES
# ==============================================================================

def get_or_create_chat_session(db: Session, cluster_id: int) -> 'ChatSession':
    """Obtém ou cria uma sessão de chat para um cluster."""
    try:
        from .database import ChatSession
    except ImportError:
        from backend.database import ChatSession
    
    session = db.query(ChatSession).filter(ChatSession.cluster_id == cluster_id).first()
    if not session:
        session = ChatSession(cluster_id=cluster_id)
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def add_chat_message(db: Session, session_id: int, role: str, content: str) -> 'ChatMessage':
    """Adiciona uma mensagem ao chat."""
    try:
        from .database import ChatMessage
    except ImportError:
        from backend.database import ChatMessage
    
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_chat_messages_by_session(db: Session, session_id: int) -> List['ChatMessage']:
    """Obtém todas as mensagens de uma sessão de chat."""
    try:
        from .database import ChatMessage
    except ImportError:
        from backend.database import ChatMessage
    
    return db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.timestamp).all()


def get_chat_session_by_cluster(db: Session, cluster_id: int) -> Optional['ChatSession']:
    """Obtém a sessão de chat de um cluster."""
    try:
        from .database import ChatSession
    except ImportError:
        from backend.database import ChatSession
    
    return db.query(ChatSession).filter(ChatSession.cluster_id == cluster_id).first()


def update_cluster_priority(db: Session, cluster_id: int, nova_prioridade: str, motivo: str = None) -> bool:
    """Atualiza a prioridade de um cluster e registra a alteração."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from backend.database import ClusterAlteracao
    
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    if not cluster:
        return False
    
    # Registra a alteração
    alteracao = ClusterAlteracao(
        cluster_id=cluster_id,
        campo_alterado='prioridade',
        valor_anterior=cluster.prioridade,
        valor_novo=nova_prioridade,
        motivo=motivo,
        usuario='sistema'
    )
    db.add(alteracao)
    
    # Atualiza o cluster
    cluster.prioridade = nova_prioridade
    cluster.updated_at = datetime.utcnow()
    
    db.commit()
    return True


def update_cluster_tags(db: Session, cluster_id: int, novas_tags: List[str], motivo: str = None) -> bool:
    """Atualiza as tags de um cluster e registra a alteração."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from backend.database import ClusterAlteracao
    
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    if not cluster:
        return False
    
    # Registra a alteração
    alteracao = ClusterAlteracao(
        cluster_id=cluster_id,
        campo_alterado='tag',
        valor_anterior=cluster.tag,
        valor_novo=', '.join(novas_tags),
        motivo=motivo,
        usuario='sistema'
    )
    db.add(alteracao)
    
    # Atualiza o cluster (usa a primeira tag como principal)
    cluster.tag = novas_tags[0] if novas_tags else cluster.tag
    cluster.updated_at = datetime.utcnow()
    
    db.commit()
    return True


def update_cluster_title(db: Session, cluster_id: int, novo_titulo: str, motivo: str = None) -> bool:
    """Atualiza o título de um cluster e registra a alteração."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from backend.database import ClusterAlteracao

    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    if not cluster:
        return False

    alteracao = ClusterAlteracao(
        cluster_id=cluster_id,
        campo_alterado='titulo_cluster',
        valor_anterior=cluster.titulo_cluster,
        valor_novo=str(novo_titulo)[:500],
        motivo=motivo,
        usuario='sistema'
    )
    db.add(alteracao)

    cluster.titulo_cluster = str(novo_titulo)[:500]
    cluster.updated_at = datetime.utcnow()
    db.commit()
    return True


def soft_delete_cluster(db: Session, cluster_id: int, motivo: str = None) -> bool:
    """Arquiva (soft delete) um cluster marcando status='descartado' e registra alteração."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from backend.database import ClusterAlteracao

    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    if not cluster:
        return False

    alteracao = ClusterAlteracao(
        cluster_id=cluster_id,
        campo_alterado='status',
        valor_anterior=cluster.status,
        valor_novo='descartado',
        motivo=motivo or 'merge de consolidação',
        usuario='sistema'
    )
    db.add(alteracao)

    cluster.status = 'descartado'
    cluster.updated_at = datetime.utcnow()
    db.commit()
    return True


def merge_clusters(db: Session, destino_id: int, fontes_ids: List[int],
                   novo_titulo: Optional[str] = None,
                   nova_tag: Optional[str] = None,
                   nova_prioridade: Optional[str] = None,
                   motivo: str = 'merge de consolidação') -> Dict[str, Any]:
    """
    Consolida múltiplos clusters "fontes" dentro de um cluster "destino":
    - Reatribui todos os artigos dos clusters fontes para o destino
    - Atualiza métricas do destino
    - Opcionalmente ajusta título, tag e prioridade do destino
    - Marca clusters fontes como descartados (soft delete)
    Retorna um dicionário com contagens de artigos movidos e clusters encerrados.
    """
    resultado = {"artigos_movidos": 0, "clusters_descartados": 0}

    destino = db.query(ClusterEvento).filter(ClusterEvento.id == destino_id, ClusterEvento.status == 'ativo').first()
    if not destino:
        return resultado

    # Reatribui artigos das fontes
    for cid in fontes_ids:
        if cid == destino_id:
            continue
        fonte = db.query(ClusterEvento).filter(ClusterEvento.id == cid, ClusterEvento.status == 'ativo').first()
        if not fonte:
            continue
        artigos = get_artigos_by_cluster(db, cid)
        for art in artigos:
            associate_artigo_to_cluster(db, art.id, destino_id)
            resultado["artigos_movidos"] += 1

        # Soft delete da fonte
        if soft_delete_cluster(db, cid, motivo=motivo):
            resultado["clusters_descartados"] += 1

    # Ajustes opcionais no destino
    if novo_titulo:
        update_cluster_title(db, destino_id, novo_titulo, motivo)
    if nova_tag:
        update_cluster_tags(db, destino_id, [nova_tag], motivo)
    if nova_prioridade:
        update_cluster_priority(db, destino_id, nova_prioridade, motivo)

    # Recalcula total_artigos e embedding_medio do destino
    artigos_destino = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == destino_id).all()
    destino.total_artigos = len(artigos_destino)
    try:
        import numpy as np
        emb_list = []
        for a in artigos_destino:
            if a.embedding:
                try:
                    from .processing import bytes_to_embedding as _b2e  # type: ignore
                except Exception:
                    from backend.processing import bytes_to_embedding as _b2e  # type: ignore
                emb_list.append(_b2e(a.embedding))
        if emb_list:
            destino.embedding_medio = np.mean(emb_list, axis=0).tobytes()
    except Exception:
        pass

    destino.updated_at = datetime.utcnow()
    db.commit()

    return resultado


def get_cluster_alteracoes(db: Session, cluster_id: int) -> List['ClusterAlteracao']:
    """Obtém todas as alterações de um cluster."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from backend.database import ClusterAlteracao
    
    return db.query(ClusterAlteracao).filter(
        ClusterAlteracao.cluster_id == cluster_id
    ).order_by(ClusterAlteracao.timestamp.desc()).all()


def get_all_cluster_alteracoes(db: Session, limit: int = 100) -> List['ClusterAlteracao']:
    """Obtém todas as alterações recentes."""
    try:
        from .database import ClusterAlteracao
    except ImportError:
        from database import ClusterAlteracao
    
    return db.query(ClusterAlteracao).order_by(
        ClusterAlteracao.timestamp.desc()
    ).limit(limit).all()


# ==============================================================================
# CONTADORES POR ABA (NACIONAL/INTERNACIONAL) POR DATA
# ==============================================================================
def get_cluster_counts_by_date_and_tipo_fonte(db: Session, target_date: datetime.date) -> Dict[str, int]:
    """
    Retorna a contagem de clusters exibíveis (status ativo, não irrelevantes) por tipo_fonte
    para uma data específica.
    """
    filtros_base = [
        func.date(ClusterEvento.created_at) == target_date,
        ClusterEvento.status == 'ativo',
        ClusterEvento.prioridade != 'IRRELEVANTE',
        ClusterEvento.tag != 'IRRELEVANTE',
    ]

    # Novas categorias
    brasil_fisico = db.query(func.count(ClusterEvento.id)).filter(
        *filtros_base,
        ClusterEvento.tipo_fonte == 'brasil_fisico'
    ).scalar() or 0

    brasil_online = db.query(func.count(ClusterEvento.id)).filter(
        *filtros_base,
        ClusterEvento.tipo_fonte == 'brasil_online'
    ).scalar() or 0

    # Legado 'nacional' (itens antigos)
    nacional_legado = db.query(func.count(ClusterEvento.id)).filter(
        *filtros_base,
        ClusterEvento.tipo_fonte == 'nacional'
    ).scalar() or 0

    internacional = db.query(func.count(ClusterEvento.id)).filter(
        *filtros_base,
        ClusterEvento.tipo_fonte == 'internacional'
    ).scalar() or 0

    # Aba antiga 'nacional' (compat) = físico + online atuais + legado
    nacional_total = (brasil_fisico + brasil_online + nacional_legado)

    return {
        "brasil_fisico": int(brasil_fisico),
        "brasil_online": int(brasil_online),
        "internacional": int(internacional),
        # chaves legadas
        "nacional": int(nacional_total)
    }


# ==============================================================================
# PROMPTS CONFIGURÁVEIS: TAGS, PRIORIDADES, TEMPLATES
# ==============================================================================

def list_prompt_tags(db: Session, tipo_fonte: Optional[str] = None) -> List[Dict[str, Any]]:
    q = db.query(PromptTag)
    if tipo_fonte:
        q = q.filter(PromptTag.tipo_fonte == tipo_fonte)
    rows = q.order_by(PromptTag.ordem.asc(), PromptTag.nome.asc()).all()
    return [
        {
            "id": r.id,
            "nome": r.nome,
            "descricao": r.descricao,
            "exemplos": r.exemplos or [],
            "ordem": r.ordem,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def get_prompt_tag_by_id(db: Session, tag_id: int) -> Optional[PromptTag]:
    return db.query(PromptTag).filter(PromptTag.id == tag_id).first()


def get_prompt_tag_by_name(db: Session, nome: str) -> Optional[PromptTag]:
    return db.query(PromptTag).filter(PromptTag.nome == nome).first()


def create_prompt_tag(db: Session, nome: str, descricao: str, exemplos: Optional[List[str]] = None, ordem: int = 0, tipo_fonte: str = 'nacional') -> int:
    existing = get_prompt_tag_by_name(db, nome)
    if existing:
        return existing.id
    row = PromptTag(nome=nome, descricao=descricao, exemplos=exemplos or [], ordem=ordem, tipo_fonte=tipo_fonte)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def update_prompt_tag(db: Session, tag_id: int, **kwargs) -> bool:
    row = get_prompt_tag_by_id(db, tag_id)
    if not row:
        return False
    for k, v in kwargs.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    db.commit()
    return True


def delete_prompt_tag(db: Session, tag_id: int) -> bool:
    row = get_prompt_tag_by_id(db, tag_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def list_prompt_prioridade_itens_grouped(db: Session, tipo_fonte: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    q = db.query(PromptPrioridadeItem)
    if tipo_fonte:
        q = q.filter(PromptPrioridadeItem.tipo_fonte == tipo_fonte)
    rows = q.order_by(PromptPrioridadeItem.nivel.asc(), PromptPrioridadeItem.ordem.asc(), PromptPrioridadeItem.id.asc()).all()
    grouped: Dict[str, List[Dict[str, Any]]] = {"P1": [], "P2": [], "P3": []}
    for r in rows:
        key = (r.nivel or '').upper()
        if key not in grouped:
            grouped[key] = []
        grouped[key].append({
            "id": r.id,
            "nivel": key,
            "texto": r.texto,
            "ordem": r.ordem,
        })
    return grouped


def create_prompt_prioridade_item(db: Session, nivel: str, texto: str, ordem: int = 0, tipo_fonte: str = 'nacional') -> int:
    nivel_up = (nivel or '').upper()
    if nivel_up not in ("P1", "P2", "P3"):
        nivel_up = "P3"
    row = PromptPrioridadeItem(nivel=nivel_up, texto=texto, ordem=ordem, tipo_fonte=tipo_fonte)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def update_prompt_prioridade_item(db: Session, item_id: int, **kwargs) -> bool:
    row = db.query(PromptPrioridadeItem).filter(PromptPrioridadeItem.id == item_id).first()
    if not row:
        return False
    for k, v in kwargs.items():
        if hasattr(row, k) and v is not None:
            setattr(row, k, v)
    # normaliza nivel
    row.nivel = (row.nivel or '').upper()
    if row.nivel not in ("P1", "P2", "P3"):
        row.nivel = "P3"
    db.commit()
    return True


def delete_prompt_prioridade_item(db: Session, item_id: int) -> bool:
    row = db.query(PromptPrioridadeItem).filter(PromptPrioridadeItem.id == item_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def list_prompt_templates(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(PromptTemplate).order_by(PromptTemplate.chave.asc()).all()
    return [
        {
            "id": r.id,
            "chave": r.chave,
            "descricao": r.descricao,
            "conteudo": r.conteudo,
        }
        for r in rows
    ]


def get_prompt_template_by_key(db: Session, chave: str) -> Optional[PromptTemplate]:
    return db.query(PromptTemplate).filter(PromptTemplate.chave == chave).first()


def upsert_prompt_template(db: Session, chave: str, conteudo: str, descricao: Optional[str] = None) -> int:
    row = get_prompt_template_by_key(db, chave)
    if row:
        row.conteudo = conteudo
        if descricao is not None:
            row.descricao = descricao
        db.commit()
        return row.id
    row = PromptTemplate(chave=chave, conteudo=conteudo, descricao=descricao)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def delete_prompt_template(db: Session, template_id: int) -> bool:
    row = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def get_prompts_compilados(db: Session) -> Dict[str, Any]:
    """
    Retorna as estruturas exatamente no formato esperado por backend/prompts.py:
    - TAGS_SPECIAL_SITUATIONS: dict { tag: { descricao: str, exemplos: [str,...] } }
    - P1_ITENS, P2_ITENS, P3_ITENS: listas de strings (ordenadas)
    """
    tags_rows = db.query(PromptTag).order_by(PromptTag.ordem.asc(), PromptTag.nome.asc()).all()
    tags_dict: Dict[str, Dict[str, Any]] = {}
    for r in tags_rows:
        tags_dict[r.nome] = {
            'descricao': r.descricao,
            'exemplos': r.exemplos or []
        }

    pr_rows = db.query(PromptPrioridadeItem).order_by(PromptPrioridadeItem.nivel.asc(), PromptPrioridadeItem.ordem.asc(), PromptPrioridadeItem.id.asc()).all()
    p1: List[str] = []
    p2: List[str] = []
    p3: List[str] = []
    for r in pr_rows:
        n = (r.nivel or '').upper()
        # Aceita tanto rótulos curtos (P1/P2/P3) quanto nomes completos
        if n in ('P1', 'P1_CRITICO', 'P1-CRITICO'):
            p1.append(r.texto)
        elif n in ('P2', 'P2_ESTRATEGICO', 'P2-ESTRATEGICO', 'P2_ESTRATÉGICO'):
            p2.append(r.texto)
        elif n in ('P3', 'P3_MONITORAMENTO', 'P3-MONITORAMENTO'):
            p3.append(r.texto)

    return {
        'tags': tags_dict,
        'p1': p1,
        'p2': p2,
        'p3': p3,
    }


# ==============================================================================
# FUNÇÕES PARA AGRUPAMENTO INCREMENTAL
# ==============================================================================

def get_artigos_processados_hoje(db: Session) -> List[ArtigoBruto]:
    """
    Busca todos os artigos processados hoje que ainda não foram associados a clusters.
    """
    hoje = datetime.utcnow().date()
    
    return db.query(ArtigoBruto).filter(
        and_(
            ArtigoBruto.status == "processado",
            func.date(ArtigoBruto.processed_at) == hoje,
            ArtigoBruto.cluster_id.is_(None)  # Artigos não associados a clusters
        )
    ).order_by(ArtigoBruto.processed_at.asc()).all()


def get_clusters_existentes_hoje(db: Session) -> List[ClusterEvento]:
    """
    Busca todos os clusters existentes criados hoje.
    """
    hoje = datetime.utcnow().date()
    
    return db.query(ClusterEvento).filter(
        and_(
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.status == 'ativo'
        )
    ).order_by(ClusterEvento.created_at.asc()).all()


def get_cluster_com_artigos(db: Session, cluster_id: int) -> Optional[Dict[str, Any]]:
    """
    Obtém um cluster com todos os seus artigos para análise incremental.
    """
    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == cluster_id).first()
    if not cluster:
        return None
    
    artigos = get_artigos_by_cluster(db, cluster_id)
    
    return {
        "id": cluster.id,
        "titulo_cluster": cluster.titulo_cluster,
        "resumo_cluster": cluster.resumo_cluster,
        "tag": cluster.tag,
        "prioridade": cluster.prioridade,
        "artigos": [
            {
                "id": artigo.id,
                "titulo": artigo.titulo_extraido or "Sem título",
                "jornal": artigo.jornal or "Fonte desconhecida",
                "trecho": (artigo.texto_processado[:300] + "...") if len(artigo.texto_processado or "") > 300 else (artigo.texto_processado or "")
            }
            for artigo in artigos
        ]
    }


# ==============================================================================
# CRUD - Jobs de Pesquisa (Deep e Social)
# ==============================================================================

def create_deep_research_job(db: Session, cluster_id: int, query: Optional[str]) -> int:
    try:
        from .database import DeepResearchJob
    except ImportError:
        from backend.database import DeepResearchJob
    job = DeepResearchJob(cluster_id=cluster_id, query=query or None, status='PENDING', provider='gemini')
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.id


def update_deep_research_job(db: Session, job_id: int, **kwargs) -> bool:
    try:
        from .database import DeepResearchJob
    except ImportError:
        from backend.database import DeepResearchJob
    job = db.query(DeepResearchJob).filter(DeepResearchJob.id == job_id).first()
    if not job:
        return False
    for k, v in kwargs.items():
        setattr(job, k, v)
    db.commit()
    return True


def get_deep_research_job(db: Session, job_id: int):
    try:
        from .database import DeepResearchJob
    except ImportError:
        from backend.database import DeepResearchJob
    return db.query(DeepResearchJob).filter(DeepResearchJob.id == job_id).first()


def list_deep_research_jobs_by_cluster(db: Session, cluster_id: int, limit: int = 20):
    try:
        from .database import DeepResearchJob
    except ImportError:
        from backend.database import DeepResearchJob
    return db.query(DeepResearchJob).filter(DeepResearchJob.cluster_id == cluster_id).order_by(DeepResearchJob.created_at.desc()).limit(limit).all()


def create_social_research_job(db: Session, cluster_id: int, query: Optional[str]) -> int:
    try:
        from .database import SocialResearchJob
    except ImportError:
        from backend.database import SocialResearchJob
    job = SocialResearchJob(cluster_id=cluster_id, query=query or None, status='PENDING', provider='grok4')
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.id


def update_social_research_job(db: Session, job_id: int, **kwargs) -> bool:
    try:
        from .database import SocialResearchJob
    except ImportError:
        from backend.database import SocialResearchJob
    job = db.query(SocialResearchJob).filter(SocialResearchJob.id == job_id).first()
    if not job:
        return False
    for k, v in kwargs.items():
        setattr(job, k, v)
    db.commit()
    return True


def get_social_research_job(db: Session, job_id: int):
    try:
        from .database import SocialResearchJob
    except ImportError:
        from backend.database import SocialResearchJob
    return db.query(SocialResearchJob).filter(SocialResearchJob.id == job_id).first()


def list_social_research_jobs_by_cluster(db: Session, cluster_id: int, limit: int = 20):
    try:
        from .database import SocialResearchJob
    except ImportError:
        from backend.database import SocialResearchJob
    return db.query(SocialResearchJob).filter(SocialResearchJob.cluster_id == cluster_id).order_by(SocialResearchJob.created_at.desc()).limit(limit).all()


def associate_artigo_to_existing_cluster(db: Session, artigo_id: int, cluster_id: int) -> bool:
    """
    Associa um artigo a um cluster existente.
    """
    return associate_artigo_to_cluster(db, artigo_id, cluster_id)


def create_cluster_for_artigo(db: Session, artigo: ArtigoBruto, tema_principal: str) -> ClusterEvento:
    """
    Cria um novo cluster para um artigo específico.
    """
    try:
        from .models import ClusterEventoCreate
    except ImportError:
        from models import ClusterEventoCreate
    
    # Calcula embedding médio (neste caso, usa o embedding do artigo)
    embedding_medio = artigo.embedding
    
    cluster_data = ClusterEventoCreate(
        titulo_cluster=tema_principal,
        resumo_cluster=None,  # Será preenchido posteriormente
        tag=artigo.tag or "Sem categoria",
        prioridade=artigo.prioridade or "P3_MONITORAMENTO",
        embedding_medio=embedding_medio
    )
    
    cluster = create_cluster(db, cluster_data)
    
    # Associa o artigo ao cluster
    associate_artigo_to_cluster(db, artigo.id, cluster.id)
    
    return cluster