"""
Configuração do banco de dados SQLAlchemy para o BTG AlphaFeed.
Define modelos de tabelas e configuração de conexão PostgreSQL.
"""

import os
from datetime import datetime
from typing import Optional, List

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, LargeBinary, Float, JSON, Boolean, ForeignKey, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

# Detecta DATABASE_URL (Heroku) e ajusta para SQLAlchemy
def _resolve_database_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        url = env_url.strip()
        # Converte postgres:// para postgresql+psycopg2:// se necessário
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url
    # Fallback desenvolvimento local
    return "postgresql+psycopg2://postgres_local@localhost:5433/devdb"

# Configuração única (Heroku/Prod via env; Dev fallback local)
SQLALCHEMY_DATABASE_URI = _resolve_database_url()

# Cria o engine do SQLAlchemy
engine = create_engine(
    SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
)

# Cria uma classe de sessão local, que sera usada em toda a aplicacao para interagir com o banco.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para todos os modelos. Nossas classes de tabelas vao herdar desta.
Base = declarative_base()


class ArtigoBruto(Base):
    """
    Tabela para armazenar artigos brutos coletados.
    Representa a primeira etapa do pipeline antes do processamento.
    """
    __tablename__ = "artigos_brutos"
    
    id = Column(Integer, primary_key=True, index=True)
    hash_unico = Column(String(64), unique=True, nullable=False, index=True)
    texto_bruto = Column(Text, nullable=False)
    url_original = Column(String(500), nullable=True)
    fonte_coleta = Column(String(50), nullable=False)  # telegram, web, pdf
    metadados = Column(JSON, default={})
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    
    # Status do processamento
    status = Column(String(20), default='pendente', nullable=False)  # pendente, processado, irrelevante, erro
    
    # Resultados do processamento (quando relevante)
    titulo_extraido = Column(String(500), nullable=True)
    texto_processado = Column(Text, nullable=True)
    jornal = Column(String(100), nullable=True)
    autor = Column(String(200), nullable=True)
    pagina = Column(String(50), nullable=True)
    data_publicacao = Column(DateTime, nullable=True)
    categoria = Column(String(100), nullable=True)
    tag = Column(String(50), nullable=True)  # Uma das 4 tags válidas
    prioridade = Column(String(20), nullable=True)  # P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO
    relevance_score = Column(Float, nullable=True)
    relevance_reason = Column(Text, nullable=True)
    
    # Dados originais (para JSONs e PDFs processados)
    # subtitulo = Column(String(500), nullable=True)  # Subtítulo original
    # data_ultima_modificacao = Column(DateTime, nullable=True)  # Data de última modificação
    # id_hash_original = Column(String(64), nullable=True)  # ID hash original do JSON
    # fonte_original = Column(String(100), nullable=True)  # Fonte original (ex: "Valor Econômico")
    # tags_originais = Column(JSON, nullable=True)  # Tags originais como array
    
    # Tipo de fonte: nacional ou internacional
    tipo_fonte = Column(String(20), default='nacional', nullable=False)  # nacional, internacional
    
    # Embedding para clusterização (v1 - 384d hash simples)
    embedding = Column(LargeBinary, nullable=True)
    
    # Embedding v2 (768d Gemini text-embedding-004) para Graph-RAG
    embedding_v2 = Column(LargeBinary, nullable=True)
    
    # Relacionamentos
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=True)
    cluster = relationship("ClusterEvento", back_populates="artigos")
    
    # Índices para performance
    __table_args__ = (
        Index('idx_artigos_status_created', 'status', 'created_at'),
        Index('idx_artigos_hash', 'hash_unico'),
        Index('idx_artigos_fonte_data', 'fonte_coleta', 'created_at'),
        Index('idx_artigos_tag_prioridade', 'tag', 'prioridade'),
        # NOVOS ÍNDICES PARA PERFORMANCE
        Index('idx_artigos_created_date', 'created_at'),  # Índice simples por data
        Index('idx_artigos_processed_date', 'processed_at'),  # Índice por data de processamento
        Index('idx_artigos_cluster_date', 'cluster_id', 'created_at'),  # Índice composto para queries por cluster e data
        Index('idx_artigos_status_date', 'status', 'created_at'),  # Índice composto para queries por status e data
        Index('idx_artigos_tag_date', 'tag', 'created_at'),  # Índice composto para queries por tag e data
    )


class ClusterEvento(Base):
    """
    Tabela para clusters de eventos.
    Agrupa artigos relacionados ao mesmo fato gerador.
    """
    __tablename__ = "clusters_eventos"
    
    id = Column(Integer, primary_key=True, index=True)
    titulo_cluster = Column(String(500), nullable=False)
    resumo_cluster = Column(Text, nullable=True)
    
    # Classificação
    tag = Column(String(50), nullable=False)  # Uma das 4 tags válidas
    prioridade = Column(String(20), nullable=False)  # Prioridade máxima dos artigos do cluster
    
    # Embedding médio do cluster (para similaridade)
    embedding_medio = Column(LargeBinary, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Status do cluster
    status = Column(String(20), default='ativo', nullable=False)  # ativo, arquivado, descartado
    
    # Tipo de fonte: nacional ou internacional (herdado dos artigos do cluster)
    tipo_fonte = Column(String(20), default='nacional', nullable=False)  # nacional, internacional
    
    # Métricas
    total_artigos = Column(Integer, default=0, nullable=False)
    ultima_atualizacao = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Notificacao incremental (Telegram/WhatsApp)
    ja_notificado = Column(Boolean, default=False, nullable=False)
    notificado_em = Column(DateTime, nullable=True)
    
    # Relacionamentos
    artigos = relationship("ArtigoBruto", back_populates="cluster")
    
    # Índices para performance
    __table_args__ = (
        Index('idx_clusters_status_created', 'status', 'created_at'),
        Index('idx_clusters_tag_prioridade', 'tag', 'prioridade'),
        # NOVOS ÍNDICES PARA PERFORMANCE
        Index('idx_clusters_created_date', 'created_at'),  # Índice simples por data
        Index('idx_clusters_updated_date', 'updated_at'),  # Índice por data de atualização
        Index('idx_clusters_status_created_updated', 'status', 'created_at', 'updated_at'),  # Cache key: max(updated_at) WHERE status=ativo AND date(created_at)=X
        Index('idx_clusters_tag_date', 'tag', 'created_at'),  # Índice composto para queries por tag e data
        Index('idx_clusters_prioridade_date', 'prioridade', 'created_at'),  # Índice composto para queries por prioridade e data
        Index('idx_clusters_notificado', 'ja_notificado', 'created_at'),  # Clusters pendentes de notificacao
    )


class SinteseExecutiva(Base):
    """
    Tabela para sínteses executivas diárias.
    """
    __tablename__ = "sinteses_executivas"
    
    id = Column(Integer, primary_key=True, index=True)
    data_sintese = Column(DateTime, nullable=False, index=True)
    texto_sintese = Column(Text, nullable=False)
    
    # Métricas do dia
    total_noticias_coletadas = Column(Integer, default=0)
    total_eventos_unicos = Column(Integer, default=0)
    total_analises_criticas = Column(Integer, default=0)  # P1
    total_monitoramento = Column(Integer, default=0)  # P2 + P3
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index('idx_sintese_data', 'data_sintese'),
    )


class LogProcessamento(Base):
    """
    Tabela para logs de processamento e debugging.
    """
    __tablename__ = "logs_processamento"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    nivel = Column(String(10), nullable=False)  # INFO, WARNING, ERROR, DEBUG
    componente = Column(String(50), nullable=False)  # collector, processor, api
    mensagem = Column(Text, nullable=False)
    detalhes = Column(JSON, default={})
    
    # Referências opcionais
    artigo_id = Column(Integer, ForeignKey('artigos_brutos.id'), nullable=True)
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=True)
    
    __table_args__ = (
        Index('idx_logs_timestamp_nivel', 'timestamp', 'nivel'),
        Index('idx_logs_componente', 'componente'),
    )


class ConfiguracaoColeta(Base):
    """
    Tabela para configurações dos coletores.
    """
    __tablename__ = "configuracoes_coleta"
    
    id = Column(Integer, primary_key=True, index=True)
    nome_coletor = Column(String(50), nullable=False, unique=True)
    ativo = Column(Boolean, default=True, nullable=False)
    configuracao = Column(JSON, nullable=False)
    
    # Controle de execução
    ultima_execucao = Column(DateTime, nullable=True)
    proxima_execucao = Column(DateTime, nullable=True)
    intervalo_minutos = Column(Integer, default=60, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_config_coleta_nome', 'nome_coletor'),
        Index('idx_config_coleta_ativo', 'ativo'),
        Index('idx_config_coleta_execucao', 'ultima_execucao', 'proxima_execucao'),
    )


class ChatSession(Base):
    """
    Tabela para sessões de chat com clusters.
    """
    __tablename__ = "chat_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    cluster = relationship("ClusterEvento", backref="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    
    # Índices
    __table_args__ = (
        Index('idx_chat_cluster_id', 'cluster_id'),
        Index('idx_chat_created_date', 'created_at'),
        Index('idx_chat_updated_date', 'updated_at'),
    )


class ChatMessage(Base):
    """
    Tabela para mensagens do chat.
    """
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False)
    
    # Conteúdo da mensagem
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    
    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    session = relationship("ChatSession", back_populates="messages")
    
    # Índices
    __table_args__ = (
        Index('idx_chat_msg_session_id', 'session_id'),
        Index('idx_chat_msg_timestamp', 'timestamp'),
        Index('idx_chat_msg_role', 'role'),
    )


class FeedbackNoticia(Base):
    """
    Tabela para coletar feedback de usuarios sobre noticias (artigos).
    Campo metadados armazena contexto rico para analise de padroes:
    {tag, prioridade, titulo_cluster, cluster_id, entidades: [{name, type}]}
    """
    __tablename__ = "feedback_noticias"

    id = Column(Integer, primary_key=True, index=True)
    artigo_id = Column(Integer, ForeignKey('artigos_brutos.id'), nullable=False, index=True)
    feedback = Column(String(10), nullable=False)  # like | dislike
    processed = Column(Boolean, default=False, nullable=False)
    metadados = Column(JSON, default={})  # contexto rico para feedback analysis
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    artigo = relationship("ArtigoBruto")

    __table_args__ = (
        Index('idx_feedback_artigo_id', 'artigo_id'),
        Index('idx_feedback_processed', 'processed'),
        Index('idx_feedback_created_date', 'created_at'),
    )


# ===================== Estagiário (chat por dia) =====================
class EstagiarioChatSession(Base):
    __tablename__ = "estagiario_chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    data_referencia = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_estag_sess_date', 'data_referencia'),
        Index('idx_estag_sess_created', 'created_at'),
    )


class EstagiarioChatMessage(Base):
    __tablename__ = "estagiario_chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('estagiario_chat_sessions.id'), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_estag_msg_session', 'session_id'),
        Index('idx_estag_msg_timestamp', 'timestamp'),
    )


class ClusterAlteracao(Base):
    """
    Tabela para registrar alterações em clusters.
    """
    __tablename__ = "cluster_alteracoes"
    
    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=False)
    
    # Detalhes da alteração
    campo_alterado = Column(String(50), nullable=False)  # prioridade, tag, etc.
    valor_anterior = Column(Text, nullable=True)
    valor_novo = Column(Text, nullable=False)
    motivo = Column(Text, nullable=True)
    usuario = Column(String(100), default='sistema', nullable=False)
    
    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    cluster = relationship("ClusterEvento", backref="alteracoes")
    
    # Índices
    __table_args__ = (
        Index('idx_alteracao_cluster_id', 'cluster_id'),
        Index('idx_alteracao_timestamp', 'timestamp'),
        Index('idx_alteracao_campo', 'campo_alterado'),
        Index('idx_alteracao_usuario', 'usuario'),
    )


# ========================
# Prompts configuráveis (Tags/Prioridades/Templates)
# ========================

class PromptTag(Base):
    __tablename__ = "prompt_tags"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), unique=True, nullable=False, index=True)
    descricao = Column(Text, nullable=False)
    exemplos = Column(JSON, default=list)  # lista de strings
    ordem = Column(Integer, default=0, nullable=False)
    tipo_fonte = Column(String(20), default='nacional', nullable=False, index=True)  # nacional|internacional

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_prompt_tags_ordem', 'ordem'),
        Index('idx_prompt_tags_tipo_fonte', 'tipo_fonte'),
    )


# ========================
# Busca Semântica (Embeddings dedicados)
# ========================

class SemanticEmbedding(Base):
    """
    Tabela dedicada para armazenar embeddings de busca semântica por artigo.
    Mantida separada para não impactar o pipeline existente que usa `ArtigoBruto.embedding` (bytes 384d).
    """
    __tablename__ = "semantic_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    artigo_id = Column(Integer, ForeignKey('artigos_brutos.id'), nullable=False, index=True)

    # Vetor armazenado como bytes (float32 array). Dimensão registrada abaixo.
    vector_bytes = Column(LargeBinary, nullable=False)
    dimension = Column(Integer, nullable=False)

    # Metadados do provedor/modelo (ex.: provider="openai", model="text-embedding-3-small")
    provider = Column(String(50), nullable=False)
    model = Column(String(120), nullable=False, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relacionamento auxiliar
    artigo = relationship("ArtigoBruto")

    __table_args__ = (
        Index('idx_semantic_unique', 'artigo_id', 'model'),
    )


class PromptPrioridadeItem(Base):
    __tablename__ = "prompt_prioridade_itens"

    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String(20), nullable=False, index=True)  # P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO
    texto = Column(Text, nullable=False)
    ordem = Column(Integer, default=0, nullable=False)
    tipo_fonte = Column(String(20), default='nacional', nullable=False, index=True)  # nacional|internacional

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_prompt_prioridade_nivel_ordem', 'nivel', 'ordem'),
        Index('idx_prompt_prioridade_tipo_fonte', 'tipo_fonte'),
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    chave = Column(String(120), unique=True, nullable=False, index=True)  # ex: PROMPT_EXTRACAO_GATEKEEPER_V13
    descricao = Column(String(300), nullable=True)
    conteudo = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_prompt_templates_chave', 'chave'),
    )


class PromptConfig(Base):
    """
    Tabela de configuracoes dinamicas de prompts.
    Usada pelo sistema de feedback learning para armazenar regras aprendidas
    (chave: FEEDBACK_RULES) e outras configs runtime.
    
    Fluxo: analyze_feedback.py --save -> INSERT/UPSERT -> get_feedback_rules() -> leitura com cache
    """
    __tablename__ = "prompt_configs"

    id = Column(Integer, primary_key=True, index=True)
    chave = Column(String(120), unique=True, nullable=False, index=True)  # ex: FEEDBACK_RULES, CONSOLIDATION_HINTS
    valor = Column(Text, nullable=False)  # Conteudo da config (texto livre ou JSON)
    descricao = Column(Text, nullable=True)  # Metadados/contexto (JSON com analise, etc)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_prompt_configs_chave', 'chave'),
    )


# ========================
# Graph-RAG: Entidades e Arestas (v2.0)
# ========================

class GraphEntity(Base):
    """
    Tabela de Entidades do Grafo de Conhecimento.
    Armazena Pessoas, Empresas, Orgaos Governamentais e Conceitos
    com resolucao de entidades via canonical_name.
    """
    __tablename__ = "graph_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)                    # Nome como aparece no texto
    canonical_name = Column(Text, nullable=False)          # Nome normalizado (ex: "Haddad" -> "Fernando Haddad")
    entity_type = Column(String(50), nullable=False)       # PERSON, ORG, GOV, EVENT, CONCEPT
    description = Column(Text, nullable=True)              # Descricao/contexto sobre a entidade
    aliases = Column(JSON, default=list)                   # Lista de aliases conhecidos

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relacionamentos
    edges = relationship("GraphEdge", back_populates="entity", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_graph_entity_canonical', 'canonical_name', 'entity_type', unique=True),
        Index('idx_graph_entity_type', 'entity_type'),
        Index('idx_graph_entity_name', 'name'),
    )


class GraphEdge(Base):
    """
    Tabela de Arestas do Grafo de Conhecimento.
    Liga artigos existentes (artigos_brutos) as entidades (graph_entities).
    Cada aresta tem metadados como sentimento, papel e trecho de contexto.
    """
    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    artigo_id = Column(Integer, ForeignKey('artigos_brutos.id', ondelete='CASCADE'), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey('graph_entities.id', ondelete='CASCADE'), nullable=False)

    relation_type = Column(String(50), nullable=False, default='MENTIONED')  # MENTIONED, PROTAGONIST, TARGET, COADJUVANT
    sentiment_score = Column(Float, nullable=True)         # -1.0 (negativo) a 1.0 (positivo)
    context_snippet = Column(Text, nullable=True)          # Trecho do texto que justifica a ligacao
    confidence = Column(Float, default=1.0)                # Confianca da extracao (0-1)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relacionamentos
    artigo = relationship("ArtigoBruto")
    entity = relationship("GraphEntity", back_populates="edges")

    __table_args__ = (
        Index('idx_graph_edge_artigo', 'artigo_id'),
        Index('idx_graph_edge_entity', 'entity_id'),
        Index('idx_graph_edge_relation', 'relation_type'),
        Index('idx_graph_edge_artigo_entity', 'artigo_id', 'entity_id', unique=True),
    )


# ========================
# Pesquisas Assincronas
# ========================

# ========================
# Sistema de Usuários Multi-Tenant (v3.0)
# ========================

class Usuario(Base):
    """Usuário da plataforma com role-based access."""
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    email = Column(String(300), unique=True, nullable=False)
    senha_hash = Column(String(500), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # admin | user
    ativo = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    preferencias = relationship("PreferenciaUsuario", back_populates="usuario", uselist=False, cascade="all, delete-orphan")
    resumos = relationship("ResumoUsuario", back_populates="usuario", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_usuarios_email', 'email', unique=True),
        Index('idx_usuarios_role', 'role'),
        Index('idx_usuarios_ativo', 'ativo'),
    )


class PreferenciaUsuario(Base):
    """Preferências pessoais de cada usuário (filtros, tags, formato de resumo)."""
    __tablename__ = "preferencias_usuario"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), unique=True, nullable=False)
    tags_interesse = Column(JSON, default=list)
    tags_ignoradas = Column(JSON, default=list)
    fontes_ignoradas = Column(JSON, default=list)
    prioridade_minima = Column(String(30), default="P3_MONITORAMENTO", nullable=False)
    tipo_fonte_preferido = Column(String(50), nullable=True)
    tamanho_resumo = Column(String(20), default="medio", nullable=False)  # curto | medio | longo
    template_resumo_id = Column(Integer, ForeignKey("templates_resumo_usuario.id", ondelete="SET NULL"), nullable=True)
    config_extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    usuario = relationship("Usuario", back_populates="preferencias")
    template_resumo = relationship("TemplateResumoUsuario")

    __table_args__ = (
        Index('idx_prefs_user_id', 'user_id', unique=True),
    )


class TemplateResumoUsuario(Base):
    """Templates reutilizáveis de resumo. Criados por usuários, compartilháveis via flag 'publico'."""
    __tablename__ = "templates_resumo_usuario"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(200), nullable=False)
    descricao = Column(Text, nullable=True)
    criado_por_user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    publico = Column(Boolean, default=False, nullable=False)
    system_prompt = Column(Text, nullable=False)
    tools_habilitadas = Column(JSON, default=list)
    restricoes = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    criador = relationship("Usuario", foreign_keys=[criado_por_user_id])

    __table_args__ = (
        Index('idx_templates_resumo_publico', 'publico'),
        Index('idx_templates_resumo_criador', 'criado_por_user_id'),
    )


class ResumoUsuario(Base):
    """Resumos diários gerados por usuário. Um por (user_id, data_referencia)."""
    __tablename__ = "resumos_usuario"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True)
    data_referencia = Column(DateTime, nullable=False)
    template_id = Column(Integer, ForeignKey("templates_resumo_usuario.id", ondelete="SET NULL"), nullable=True)
    clusters_avaliados_ids = Column(JSON, default=list)
    clusters_escolhidos_ids = Column(JSON, default=list)
    texto_gerado = Column(Text, nullable=True)
    texto_whatsapp = Column(Text, nullable=True)
    prompt_version = Column(String(100), nullable=True)
    metadados = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    usuario = relationship("Usuario", back_populates="resumos")
    template = relationship("TemplateResumoUsuario")

    __table_args__ = (
        Index('idx_resumos_user_data', 'user_id', 'data_referencia'),
        Index('idx_resumos_created', 'created_at'),
    )


class DeepResearchJob(Base):
    """
    Job para pesquisas profundas (Google/Gemini). Executado em background e pode demorar.
    """
    __tablename__ = "deep_research_jobs"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=False, index=True)
    query = Column(Text, nullable=True)
    status = Column(String(20), default='PENDING', nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    provider = Column(String(50), default='gemini', nullable=False)
    result_text = Column(Text, nullable=True)
    result_json = Column(JSON, default={})
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    cluster = relationship("ClusterEvento")

    __table_args__ = (
        Index('idx_deepresearch_cluster_status', 'cluster_id', 'status'),
        Index('idx_deepresearch_created', 'created_at'),
    )


class SocialResearchJob(Base):
    """
    Job para pesquisas sociais (Grok/X/Twitter). Executado em background.
    """
    __tablename__ = "social_research_jobs"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey('clusters_eventos.id'), nullable=False, index=True)
    query = Column(Text, nullable=True)
    status = Column(String(20), default='PENDING', nullable=False)  # PENDING, RUNNING, COMPLETED, FAILED
    provider = Column(String(50), default='grok4', nullable=False)
    result_text = Column(Text, nullable=True)
    result_json = Column(JSON, default={})
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    cluster = relationship("ClusterEvento")

    __table_args__ = (
        Index('idx_socialresearch_cluster_status', 'cluster_id', 'status'),
        Index('idx_socialresearch_created', 'created_at'),
    )

# Função para criar todas as tabelas
def create_tables():
    """Cria todas as tabelas no banco de dados."""
    Base.metadata.create_all(bind=engine)


# Função para obter uma sessão do banco
def get_db():
    """
    Dependency injection para FastAPI.
    Fornece uma sessão do banco de dados.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Função para inicializar o banco
def init_database():
    """
    Inicializa o banco de dados criando as tabelas e dados iniciais.
    """
    print("📊 Inicializando banco de dados...")
    
    # Cria as tabelas
    create_tables()

    # Micro-migration: resumos_usuario.user_id nullable (para resumo default compartilhado)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE resumos_usuario ALTER COLUMN user_id DROP NOT NULL"))
            conn.commit()
    except Exception:
        pass
    
    # Cria uma sessão para inserir dados iniciais
    db = SessionLocal()
    try:
        # Verifica se já existem configurações de coleta
        existing_configs = db.query(ConfiguracaoColeta).count()
        
        # Seed de usuario admin (login endpoint handles auto-creation as fallback)
        try:
            admin_exists = db.query(Usuario).filter(
                Usuario.email.in_(["admin@enforcegroup.com.br", "admin@enforce.com.br"])
            ).first()
            if admin_exists and admin_exists.email == "admin@enforce.com.br":
                admin_exists.email = "admin@enforcegroup.com.br"
                db.commit()
                print("✅ Email do admin atualizado para admin@enforcegroup.com.br")
            elif not admin_exists:
                import hashlib, secrets
                _pwd = os.getenv("ADMIN_PASSWORD", "admin")
                _salt = secrets.token_hex(16)
                senha = f"{_salt}${hashlib.sha256((_salt + _pwd).encode()).hexdigest()}"
                admin_user = Usuario(
                    nome="Administrador",
                    email="admin@enforcegroup.com.br",
                    senha_hash=senha,
                    role="admin",
                    ativo=True,
                )
                db.add(admin_user)
                db.commit()
                print("✅ Usuario admin criado (admin@enforcegroup.com.br)")
        except Exception as e:
            db.rollback()
            print(f"⚠️ Seed admin falhou (login vai auto-criar): {e}")

        # Seed usuario barretti (Capital Solutions / Special Situations)
        try:
            barretti_exists = db.query(Usuario).filter(
                Usuario.email == "gabriel.barretti@btgpactual.com"
            ).first()
            if not barretti_exists:
                import hashlib, secrets
                _bpwd = os.getenv("BARRETTI_PASSWORD", "barretti")
                _bsalt = secrets.token_hex(16)
                bsenha = f"{_bsalt}${hashlib.sha256((_bsalt + _bpwd).encode()).hexdigest()}"
                barretti_user = Usuario(
                    nome="Gabriel Barretti",
                    email="gabriel.barretti@btgpactual.com",
                    senha_hash=bsenha,
                    role="user",
                    ativo=True,
                )
                db.add(barretti_user)
                db.flush()

                barretti_prefs = PreferenciaUsuario(
                    user_id=barretti_user.id,
                    tags_interesse=[],
                    tags_ignoradas=[],
                    tamanho_resumo="longo",
                    config_extra={
                        "empresas_radar": "BTG Pactual, Banco Master, Daniel Vorcaro, INSS, Credcesta",
                        "teses_juridicas": (
                            "DIP financing, reestruturacao, RJ, enforcement, "
                            "securitizacao divida ativa, good-bank/bad-bank, "
                            "liability management, preferred equity, mezzanine, rescue financing"
                        ),
                        "instrucoes_resumo": "BARRETTI_PROFILE",
                        "perfil": "barretti",
                    },
                )
                db.add(barretti_prefs)
                db.commit()
                print("✅ Usuario barretti criado (gabriel.barretti@btgpactual.com)")
        except Exception as e:
            db.rollback()
            print(f"⚠️ Seed barretti falhou: {e}")

        if existing_configs == 0:
            print("📝 Criando configurações iniciais de coleta...")
            
            # Configuração para coletor de Telegram
            config_telegram = ConfiguracaoColeta(
                nome_coletor="telegram",
                ativo=False,  # Inicia desabilitado até ser configurado
                configuracao={
                    "bot_token": "",
                    "chat_ids": [],
                    "keywords": ["Americanas", "Gerdau", "Vale", "Petrobras", "BTG"]
                },
                intervalo_minutos=15
            )
            
            # Configuração para coletor web
            config_web = ConfiguracaoColeta(
                nome_coletor="web_crawler",
                ativo=False,  # Inicia desabilitado até ser configurado
                configuracao={
                    "urls": [
                        "https://valor.globo.com/",
                        "https://www.estadao.com.br/economia/",
                        "https://www1.folha.uol.com.br/mercado/"
                    ],
                    "user_agent": "BTG AlphaFeed Bot 1.0"
                },
                intervalo_minutos=60
            )
            
            db.add(config_telegram)
            db.add(config_web)
            db.commit()
            
            print("✅ Configurações iniciais criadas com sucesso!")
        
        print("✅ Banco de dados inicializado com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
        db.rollback()
    finally:
        db.close()


# Metadados para inspeção das tabelas
def get_table_info():
    """Retorna informações sobre as tabelas criadas."""
    tables_info = {}
    for table_name, table in Base.metadata.tables.items():
        tables_info[table_name] = {
            'columns': [col.name for col in table.columns],
            'indexes': [idx.name for idx in table.indexes]
        }
    return tables_info


if __name__ == "__main__":
    # Executa a inicialização se o módulo for executado diretamente
    init_database()