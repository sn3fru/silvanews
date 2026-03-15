"""
Modelos Pydantic para validação de dados do BTG AlphaFeed.
Migrado de silva.py para arquitetura de API.
"""

from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime

# Importa as tags do prompts.py
try:
    from .prompts import TAGS_SPECIAL_SITUATIONS
except ImportError:
    # Fallback para import absoluto quando executado fora do pacote
    from backend.prompts import TAGS_SPECIAL_SITUATIONS

# Extrai as tags válidas do dicionário
TAGS_VALIDAS = list(TAGS_SPECIAL_SITUATIONS.keys())
TAGS_VALIDAS.append('IRRELEVANTE')  # Adiciona tag para notícias irrelevantes
TAGS_VALIDAS.append('PENDING')  # Adiciona tag para notícias pendentes

# Cria os tipos Literal dinamicamente
from typing import Literal
TagType = Literal[tuple(TAGS_VALIDAS)]  # type: ignore
PrioridadeType = Literal['P1_CRITICO', 'P2_ESTRATEGICO', 'P3_MONITORAMENTO', 'IRRELEVANTE', 'PENDING']

class Noticia(BaseModel):
    """Modelo de validação para notícias extraídas dos PDFs."""
    titulo: str = Field(..., min_length=1, description="Título da notícia")
    texto_completo: str = Field(..., min_length=1, description="Texto completo da notícia")
    jornal: str = Field(..., min_length=1, description="Nome do jornal")
    autor: Optional[str] = Field(default="N/A", description="Autor da notícia")
    pagina: Optional[str] = Field(default=None, description="Página onde a notícia foi encontrada")
    data: Optional[str] = Field(default=None, description="Data de publicação")
    categoria: Optional[str] = Field(default=None, description="Categoria da notícia")
    # Tag de classificação (usando as tags do TAGS_SPECIAL_SITUATIONS)
    tag: TagType
    # NOVO CAMPO: Adiciona a prioridade para filtragem
    prioridade: PrioridadeType = Field(..., description="Nível de prioridade da notícia")
    
    # --- CAMPOS PARA RANKING E EXPLAINABILITY (AGORA OPCIONAIS) ---
    relevance_score: Optional[float] = Field(default=None, ge=0, le=100, description="Score de 0 a 100 da relevância para a mesa de Special Situations.")
    relevance_reason: Optional[str] = Field(default=None, description="Justificativa curta em qual regra/assunto a notícia se encaixa.")
    
    @model_validator(mode='after')
    def model_post_init(self, __context):
        """Adiciona valores padrão para campos ausentes após a validação inicial."""
        # Normaliza o campo jornal
        if hasattr(self, 'jornal') and self.jornal:
            if self.jornal.lower() in ['folha', 'folha de s.paulo', 'folhasp']:
                self.jornal = 'Folha de S.Paulo'
            elif self.jornal.lower() in ['valor', 'valor economico']:
                self.jornal = 'Valor Econômico'
            elif self.jornal.lower() in ['estadao', 'o estado de s.paulo']:
                self.jornal = 'O Estado de S.Paulo'
        
        # Aplica migração baseada na prioridade (igual ao silva.py)
        if self.relevance_score is None or self.relevance_reason is None:
            if self.prioridade == 'P1_CRITICO':
                self.relevance_score = self.relevance_score or 85.0
                self.relevance_reason = self.relevance_reason or "Migrado: Classificado como P1_CRITICO"
            elif self.prioridade == 'P2_ESTRATEGICO':
                self.relevance_score = self.relevance_score or 65.0
                self.relevance_reason = self.relevance_reason or "Migrado: Classificado como P2_ESTRATEGICO"
            else:  # P3_MONITORAMENTO
                self.relevance_score = self.relevance_score or 35.0
                self.relevance_reason = self.relevance_reason or "Migrado: Classificado como P3_MONITORAMENTO"
        
        return self


class NoticiaResumida(BaseModel):
    """Modelo para notícias resumidas usadas no agrupamento."""
    titulo: str = Field(..., min_length=1, description="Título da notícia")
    jornal: str = Field(..., min_length=1, description="Nome do jornal")
    pagina: Optional[str] = Field(default=None, description="Página da notícia")
    prioridade: PrioridadeType


class FatoGeradorContract(BaseModel):
    """
    Contrato para extração de fato gerador (Etapa 1). Dados estruturados (entidade_alvo + acao_material)
    para agrupamento lógico. fato_gerador_padronizado é derivado para compatibilidade com leitores antigos.
    """
    entidade_alvo: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Sujeito/objeto principal do evento (máx. 5 palavras). Ex: Banco Master, Amazon."
    )
    acao_material: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="O que aconteceu concretamente (máx. 10 palavras). Ex: Decreta falência, Anuncia investimento."
    )
    valor_financeiro: str = Field(
        default="N/A",
        max_length=80,
        description="Valor monetário se existir (ex: $18 bilhões), senão N/A."
    )
    # Retrocompatibilidade: leitores que esperam uma única string (entidade_alvo - acao_material)
    fato_gerador_padronizado: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Derivado: entidade_alvo - acao_material. Preenchido ao salvar no pipeline."
    )


class FonteResumo(BaseModel):
    """Modelo para fontes de um resumo."""
    jornal: Optional[str] = Field(default=None, description="Nome do jornal")
    pagina: Optional[str] = Field(default=None, description="Página da notícia")
    autor: Optional[str] = Field(default=None, description="Autor da notícia")


class ResumoFinal(BaseModel):
    """Modelo de validação para resumos finais."""
    titulo_final: str = Field(..., min_length=1, description="Título final do resumo")
    resumo_final: str = Field(..., min_length=1, description="Resumo consolidado")
    fontes: Optional[List[FonteResumo]] = Field(default=[], description="Lista de fontes")
    tag: TagType
    # NOVO CAMPO: Adiciona a prioridade para ordenação do relatório
    prioridade: PrioridadeType = Field(..., description="Prioridade máxima do grupo de notícias")


# --- MODELOS PARA A API ---

class ArtigoBrutoCreate(BaseModel):
    """Modelo para criação de artigos brutos no banco."""
    hash_unico: str = Field(..., description="Hash único do artigo")
    texto_bruto: str = Field(..., description="Texto original do artigo")
    url_original: Optional[str] = Field(default=None, description="URL original do artigo")
    fonte_coleta: str = Field(..., description="Fonte da coleta (telegram, web, pdf)")
    metadados: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadados adicionais")


class ClusterEventoCreate(BaseModel):
    """Modelo para criação de clusters de eventos."""
    titulo_cluster: str = Field(..., description="Título do cluster")
    resumo_cluster: Optional[str] = Field(default=None, description="Resumo do cluster")
    tag: TagType
    prioridade: PrioridadeType
    embedding_medio: Optional[bytes] = Field(default=None, description="Embedding médio do cluster")
    tipo_fonte: Optional[str] = Field(default='nacional', description="Tipo de fonte: nacional ou internacional")


class FeedResponse(BaseModel):
    """Modelo de resposta para o endpoint /api/feed."""
    metricas: Dict[str, int] = Field(..., description="Métricas do dia")
    sintese_dia: str = Field(..., description="Síntese executiva do dia")
    feed: List[Dict[str, Any]] = Field(..., description="Lista de clusters para o feed")


class ClusterDetalhes(BaseModel):
    """Modelo para detalhes de um cluster específico."""
    id: int
    titulo_final: str
    resumo_final: str
    prioridade: PrioridadeType
    tag: TagType
    fontes: List[Dict[str, Any]]
    timestamp: str


class ProcessarArtigoRequest(BaseModel):
    """Modelo para requisição de processamento de artigo."""
    id_artigo: int = Field(..., description="ID do artigo a ser processado")


class StatusResponse(BaseModel):
    """Modelo para respostas de status."""
    status: str = Field(..., description="Status da operação")
    message: str = Field(..., description="Mensagem descritiva")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Dados adicionais")


# --- MODELOS PARA MIGRAÇÃO DE CACHE ---

class NoticiaCacheLegacy(BaseModel):
    """Modelo para validação de notícias do cache legado."""
    titulo: str
    texto_completo: str
    jornal: str
    autor: Optional[str] = "N/A"
    pagina: Optional[str] = None
    data: Optional[str] = None
    categoria: Optional[str] = None
    tag: Optional[str] = None
    prioridade: Optional[str] = None
    relevance_score: Optional[float] = None
    relevance_reason: Optional[str] = None


# --- MODELOS PARA CHAT E ALTERAÇÕES ---

class ChatMessage(BaseModel):
    """Modelo para mensagens do chat."""
    role: Literal['user', 'assistant', 'system'] = Field(..., description="Papel da mensagem")
    content: str = Field(..., description="Conteúdo da mensagem")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Timestamp da mensagem")


class ChatSession(BaseModel):
    """Modelo para sessões de chat."""
    id: Optional[int] = Field(default=None, description="ID da sessão")
    cluster_id: int = Field(..., description="ID do cluster relacionado")
    messages: List[ChatMessage] = Field(default_factory=list, description="Lista de mensagens")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Data de criação")
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Data de atualização")


class ChatRequest(BaseModel):
    """Modelo para requisições de chat."""
    cluster_id: int = Field(..., description="ID do cluster")
    message: str = Field(..., description="Mensagem do usuário")
    session_id: Optional[int] = Field(default=None, description="ID da sessão (se existir)")


class ChatResponse(BaseModel):
    """Modelo para respostas do chat."""
    session_id: int = Field(..., description="ID da sessão")
    response: str = Field(..., description="Resposta do assistente")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp da resposta")


class ResearchJobCreate(BaseModel):
    cluster_id: int
    query: Optional[str] = None


class ResearchJobStatus(BaseModel):
    id: int
    cluster_id: int
    status: Literal['PENDING', 'RUNNING', 'COMPLETED', 'FAILED']
    provider: str
    result_text: Optional[str] = None
    result_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime

class ClusterAlteracao(BaseModel):
    """Modelo para alterações em clusters."""
    cluster_id: int = Field(..., description="ID do cluster")
    campo_alterado: str = Field(..., description="Campo que foi alterado")
    valor_anterior: Optional[str] = Field(default=None, description="Valor anterior")
    valor_novo: str = Field(..., description="Novo valor")
    motivo: Optional[str] = Field(default=None, description="Motivo da alteração")
    usuario: Optional[str] = Field(default="sistema", description="Usuário que fez a alteração")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Timestamp da alteração")


class ClusterUpdateRequest(BaseModel):
    """Modelo para requisições de atualização de cluster."""
    cluster_id: int = Field(..., description="ID do cluster")
    prioridade: Optional[PrioridadeType] = Field(default=None, description="Nova prioridade")
    tags: Optional[List[str]] = Field(default=None, description="Novas tags")
    motivo: Optional[str] = Field(default=None, description="Motivo da alteração")


class FeedbackCreate(BaseModel):
    artigo_id: int
    feedback: Literal['like', 'dislike']


class FeedbackItem(BaseModel):
    id: int
    artigo_id: int
    feedback: Literal['like', 'dislike']
    processed: bool
    created_at: datetime


# --- MODELOS PARA SISTEMA DE USUARIOS (v3.0 Multi-Tenant) ---

class LoginRequest(BaseModel):
    """Credenciais de login."""
    email: str = Field(..., description="Email ou username do usuário")
    senha: str = Field(..., description="Senha do usuário")


class TokenResponse(BaseModel):
    """JWT token retornado no login."""
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class UsuarioCreate(BaseModel):
    """Criação de novo usuário (admin only)."""
    nome: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=300)
    senha: str = Field(..., min_length=4, max_length=200)
    role: Literal['admin', 'user'] = 'user'


class UsuarioUpdate(BaseModel):
    """Atualização de perfil."""
    nome: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=300)
    senha: Optional[str] = Field(default=None, min_length=4, max_length=200)


class UsuarioResponse(BaseModel):
    """Dados públicos de um usuário."""
    id: int
    nome: str
    email: str
    role: str
    ativo: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PreferenciasUpdate(BaseModel):
    """Atualização de preferências do usuário."""
    tags_interesse: Optional[List[str]] = None
    tags_ignoradas: Optional[List[str]] = None
    fontes_ignoradas: Optional[List[str]] = None
    prioridade_minima: Optional[str] = None
    tipo_fonte_preferido: Optional[str] = None
    tamanho_resumo: Optional[Literal['curto', 'medio', 'longo']] = None
    template_resumo_id: Optional[int] = None
    config_extra: Optional[Dict[str, Any]] = None


class PreferenciasResponse(BaseModel):
    """Preferências do usuário."""
    id: int
    user_id: int
    tags_interesse: List[str] = []
    tags_ignoradas: List[str] = []
    fontes_ignoradas: List[str] = []
    prioridade_minima: str = "P3_MONITORAMENTO"
    tipo_fonte_preferido: Optional[str] = None
    tamanho_resumo: str = "medio"
    template_resumo_id: Optional[int] = None
    config_extra: Dict[str, Any] = {}

    model_config = {"from_attributes": True}


class TemplateResumoCreate(BaseModel):
    """Criação de template de resumo."""
    nome: str = Field(..., min_length=2, max_length=200)
    descricao: Optional[str] = None
    system_prompt: str = Field(..., min_length=10)
    publico: bool = False
    tools_habilitadas: List[str] = []
    restricoes: Dict[str, Any] = {}


class TemplateResumoUpdate(BaseModel):
    """Atualização de template de resumo."""
    nome: Optional[str] = Field(default=None, max_length=200)
    descricao: Optional[str] = None
    system_prompt: Optional[str] = None
    publico: Optional[bool] = None
    tools_habilitadas: Optional[List[str]] = None
    restricoes: Optional[Dict[str, Any]] = None


class TemplateResumoResponse(BaseModel):
    """Dados de um template de resumo."""
    id: int
    nome: str
    descricao: Optional[str] = None
    criado_por_user_id: Optional[int] = None
    publico: bool
    system_prompt: str
    tools_habilitadas: List[str] = []
    restricoes: Dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumoUsuarioResponse(BaseModel):
    """Resumo diário gerado para um usuário."""
    id: int
    user_id: int
    data_referencia: datetime
    template_id: Optional[int] = None
    clusters_avaliados_ids: List[int] = []
    clusters_escolhidos_ids: List[int] = []
    texto_gerado: Optional[str] = None
    texto_whatsapp: Optional[str] = None
    prompt_version: Optional[str] = None
    metadados: Dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}