"""
LangGraph Nodes for the Graph-RAG Agentic Pipeline (v2.0).

Each node encapsulates a step of the processing pipeline:
- gatekeeper_node: Hard filter (regex) + LLM classification (wraps Gatekeeper V13)
- entity_extraction_node: Extract entities from article text via LLM
- entity_resolution_node: Resolve and persist entities in the knowledge graph
- historian_node: Retrieve historical context from the graph (Graph-RAG)
- writer_node: Generate summary with historical context
- cluster_manager_node: Assign article to cluster (incremental clustering)
"""

import re
import json
import os
from typing import Dict, Any, List, Optional, TypedDict
from datetime import datetime

try:
    from ..utils import (
        extrair_json_da_resposta,
        corrigir_tag_invalida,
        corrigir_prioridade_invalida,
        get_gemini_model,
        get_date_brasil_str,
    )
    from ..prompts import (
        TAGS_SPECIAL_SITUATIONS,
        TAGS_SPECIAL_SITUATIONS_INTERNACIONAL,
    )
    from ..database import SessionLocal, ArtigoBruto
    from .graph_crud import (
        link_artigo_to_entities,
        get_historical_context_for_entities,
        get_vector_context_for_article,
    )
    from ..processing import gerar_embedding_v2
except ImportError:
    from backend.utils import (
        extrair_json_da_resposta,
        corrigir_tag_invalida,
        corrigir_prioridade_invalida,
        get_gemini_model,
        get_date_brasil_str,
    )
    from backend.prompts import (
        TAGS_SPECIAL_SITUATIONS,
        TAGS_SPECIAL_SITUATIONS_INTERNACIONAL,
    )
    from backend.database import SessionLocal, ArtigoBruto
    from backend.agents.graph_crud import (
        link_artigo_to_entities,
        get_historical_context_for_entities,
        get_vector_context_for_article,
    )
    from backend.processing import gerar_embedding_v2


# ==============================================================================
# ESTADO DO PIPELINE (TypedDict para LangGraph)
# ==============================================================================

class FeedState(TypedDict, total=False):
    """Estado que viaja entre os nos do grafo LangGraph."""
    # Dados do artigo
    artigo_id: int
    texto_raw: str
    titulo: str
    jornal: str
    tipo_fonte: str          # nacional / internacional
    metadados: dict

    # Resultado do Gatekeeper
    is_relevant: bool
    classificacao: dict       # { prioridade, tag, justificativa }
    rejection_reason: str

    # Entidades extraidas
    entities_raw: list        # Lista de dicts { name, type, role, sentiment, context }
    entities_resolved: list   # Lista de entity_ids apos resolucao

    # Contexto historico (Graph-RAG)
    contexto_historico: str   # Texto formatado com fatos passados

    # Resumo final
    resumo_final: str
    resumo_metadata: dict

    # Cluster
    cluster_id: int
    cluster_action: str       # "created" / "appended" / "none"

    # Controle
    error: str
    processing_log: list


# ==============================================================================
# REGEX HARD FILTERS (Pre-LLM, economia de tokens)
# ==============================================================================

# Padroes de ruido que nao precisam ir ao LLM
NOISE_PATTERNS = [
    r'\b(?:hor[oó]scopo|signo|astr[oó]logo|signo de)\b',
    r'\b(?:classificados|an[uú]ncios? classificados?)\b',
    r'\b(?:obitu[aá]rio|faleceu|missa de s[eé]timo)\b',
    r'\b(?:palavras? cruzadas?|sudoku|quadrinhos|tirinhas?)\b',
    r'\b(?:resultado do jogo|placar final|campeonato brasileiro|libertadores|s[eé]rie [ab])\b',
    r'\b(?:big brother|bbb\d+|novela|capitulo de)\b',
    r'\b(?:receita de bolo|culinaria|gastronomia)\b',
    r'\b(?:previs[aã]o do tempo|meteorologia|chuva forte)\b',
]

COMPILED_NOISE = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]


def _is_noise(text: str) -> bool:
    """Verifica se o texto contem padroes de ruido obvio."""
    text_lower = text[:2000].lower()  # Verifica apenas os primeiros 2000 chars
    for pattern in COMPILED_NOISE:
        if pattern.search(text_lower):
            return True
    return False


# ==============================================================================
# PROMPT DE EXTRACAO DE ENTIDADES
# ==============================================================================

PROMPT_ENTITY_EXTRACTION = """Voce e um especialista em NER (Named Entity Recognition) para o mercado financeiro brasileiro.

Dado o texto abaixo, extraia TODAS as entidades relevantes (pessoas, empresas, orgaos governamentais, eventos e conceitos).

REGRAS:
1. Extraia apenas entidades CONCRETAS e NOMEADAS (nao adjetivos ou descricoes genericas)
2. Para cada entidade, indique:
   - name: Nome como aparece no texto
   - type: PERSON | ORG | GOV | EVENT | CONCEPT
   - role: PROTAGONIST (principal no evento) | TARGET (alvo/afetado) | MENTIONED (citado)
   - sentiment: float de -1.0 (negativo) a 1.0 (positivo) baseado no contexto
   - context: Trecho curto (max 100 chars) que justifica a entidade
3. Limite: maximo 15 entidades por artigo
4. Ignore entidades genericas como "governo", "mercado", "analistas"

TEXTO:
{texto}

Responda APENAS com JSON valido no formato:
```json
{{
  "entities": [
    {{
      "name": "nome da entidade",
      "type": "PERSON|ORG|GOV|EVENT|CONCEPT",
      "role": "PROTAGONIST|TARGET|MENTIONED",
      "sentiment": 0.0,
      "context": "trecho curto do texto"
    }}
  ]
}}
```"""


# ==============================================================================
# NODE 1: GATEKEEPER (Filtro de Relevancia)
# ==============================================================================

def gatekeeper_node(state: FeedState) -> FeedState:
    """
    No 1 do pipeline: Filtro de relevancia.
    
    1. Hard filter via regex (sem LLM, economia de tokens)
    2. Se passar, a classificacao de prioridade/tag e feita na Etapa 3
       do pipeline existente (PROMPT_EXTRACAO_GATEKEEPER_V13)
    
    Este no PRESERVA o pipeline existente e adiciona apenas o filtro rapido.
    """
    log = state.get("processing_log", [])
    texto = state.get("texto_raw", "")
    titulo = state.get("titulo", "")
    
    # 1. Hard filter (Regex - Zero tokens)
    texto_completo = f"{titulo} {texto[:3000]}"
    if _is_noise(texto_completo):
        log.append(f"[Gatekeeper] Rejeitado por regex: ruido detectado")
        return {
            **state,
            "is_relevant": False,
            "rejection_reason": "Regex noise filter",
            "processing_log": log,
        }
    
    # 2. Verificacoes basicas de qualidade
    if len(texto.strip()) < 50:
        log.append(f"[Gatekeeper] Rejeitado: texto muito curto ({len(texto)} chars)")
        return {
            **state,
            "is_relevant": False,
            "rejection_reason": "Texto muito curto",
            "processing_log": log,
        }
    
    # 3. Aprovado para proximo no
    log.append(f"[Gatekeeper] Aprovado para processamento")
    return {
        **state,
        "is_relevant": True,
        "rejection_reason": "",
        "processing_log": log,
    }


# ==============================================================================
# NODE 2: ENTITY EXTRACTION (Extracao de Entidades via LLM)
# ==============================================================================

def entity_extraction_node(state: FeedState) -> FeedState:
    """
    No 2: Extrai entidades do texto via LLM (Gemini Flash).
    Identifica pessoas, empresas, orgaos e conceitos mencionados.
    """
    log = state.get("processing_log", [])
    texto = state.get("texto_raw", "")
    titulo = state.get("titulo", "")
    
    texto_para_ner = f"Titulo: {titulo}\n\n{texto[:4000]}"
    
    try:
        model = get_gemini_model()
        if not model:
            log.append("[EntityExtraction] Gemini indisponivel, pulando NER")
            return {**state, "entities_raw": [], "processing_log": log}
        
        prompt = PROMPT_ENTITY_EXTRACTION.format(texto=texto_para_ner)
        
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.2,
                'max_output_tokens': 2048,
            }
        )
        
        resultado = extrair_json_da_resposta(response.text)
        
        if resultado and isinstance(resultado, dict):
            entities = resultado.get("entities", [])
            # Validacao basica
            valid_entities = []
            for e in entities:
                if isinstance(e, dict) and e.get("name") and len(e["name"].strip()) >= 2:
                    valid_entities.append({
                        "name": e["name"].strip(),
                        "type": e.get("type", "ORG").upper(),
                        "role": e.get("role", "MENTIONED").upper(),
                        "sentiment": float(e.get("sentiment", 0.0)),
                        "context": str(e.get("context", ""))[:200],
                    })
            
            log.append(f"[EntityExtraction] {len(valid_entities)} entidades extraidas")
            return {**state, "entities_raw": valid_entities, "processing_log": log}
        else:
            log.append("[EntityExtraction] Resposta LLM nao parseavel")
            return {**state, "entities_raw": [], "processing_log": log}
    
    except Exception as e:
        log.append(f"[EntityExtraction] Erro: {str(e)[:200]}")
        return {**state, "entities_raw": [], "processing_log": log}


# ==============================================================================
# NODE 3: ENTITY RESOLUTION (Normalizacao e Persistencia no Grafo)
# ==============================================================================

def entity_resolution_node(state: FeedState) -> FeedState:
    """
    No 3: Resolve entidades extraidas (normaliza nomes) e persiste no grafo.
    Usa canonical_name e busca fuzzy para evitar duplicatas.
    """
    log = state.get("processing_log", [])
    artigo_id = state.get("artigo_id")
    entities_raw = state.get("entities_raw", [])
    
    if not entities_raw or not artigo_id:
        log.append("[EntityResolution] Nenhuma entidade para resolver")
        return {**state, "entities_resolved": [], "processing_log": log}
    
    try:
        db = SessionLocal()
        try:
            edges = link_artigo_to_entities(db, artigo_id, entities_raw)
            entity_ids = [str(e.entity_id) for e in edges]
            entity_names = [ent["name"] for ent in entities_raw]
            
            log.append(f"[EntityResolution] {len(edges)} arestas criadas no grafo")
            return {
                **state,
                "entities_resolved": entity_ids,
                "entities_raw": entities_raw,  # Preserva para historian
                "processing_log": log,
            }
        finally:
            db.close()
    
    except Exception as e:
        log.append(f"[EntityResolution] Erro: {str(e)[:200]}")
        return {**state, "entities_resolved": [], "processing_log": log}


# ==============================================================================
# NODE 4: HISTORIAN (Graph-RAG Retrieval - Cerebro Temporal)
# ==============================================================================

def historian_node(state: FeedState) -> FeedState:
    """
    No 4: O "Pulo do Gato" - Busca contexto historico no grafo + espaco vetorial.
    
    Executa 3 etapas:
    1. Gera embedding_v2 (Gemini 768d) e salva no artigo
    2. SQL temporal: clusters dos ultimos 7 dias conectados as mesmas entidades (Grafo)
    3. Busca vetorial: artigos semanticamente similares dos ultimos 30 dias (Embedding)
    4. Combina ambos em CONTEXTO_HISTORICO
    """
    log = state.get("processing_log", [])
    entities_raw = state.get("entities_raw", [])
    artigo_id = state.get("artigo_id")
    texto = state.get("texto_raw", "")
    
    contexto_parts = []
    embedding_bytes = None
    
    try:
        db = SessionLocal()
        try:
            # ---------------------------------------------------------------
            # ETAPA A: Gerar e salvar embedding_v2 (Gemini 768d)
            # ---------------------------------------------------------------
            if texto and artigo_id:
                embedding_bytes = gerar_embedding_v2(texto)
                if embedding_bytes:
                    artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == artigo_id).first()
                    if artigo:
                        artigo.embedding_v2 = embedding_bytes
                        db.commit()
                        log.append(f"[Historian] Embedding v2 gerado e salvo ({len(embedding_bytes)} bytes)")
                else:
                    log.append("[Historian] Embedding v2 nao gerado (erro ou texto curto)")
            
            # ---------------------------------------------------------------
            # ETAPA B: Busca temporal no Grafo (SQL via entidades)
            # ---------------------------------------------------------------
            if entities_raw:
                entity_names = [e["name"] for e in entities_raw if e.get("role") in ("PROTAGONIST", "TARGET")]
                if not entity_names:
                    entity_names = [e["name"] for e in entities_raw[:3]]
                
                contexto_grafo = get_historical_context_for_entities(
                    db=db,
                    entity_names=entity_names,
                    days=7,
                    max_results=5,
                )
                
                if contexto_grafo:
                    contexto_parts.append(f"=== CONTEXTO DO GRAFO (entidades relacionadas, 7 dias) ===\n{contexto_grafo}")
                    log.append(f"[Historian] Contexto grafo: {len(contexto_grafo)} chars")
                else:
                    log.append("[Historian] Grafo: nenhum contexto encontrado")
            else:
                log.append("[Historian] Sem entidades para buscar no grafo")
            
            # ---------------------------------------------------------------
            # ETAPA C: Busca vetorial (cosine similarity via embedding_v2)
            # ---------------------------------------------------------------
            if embedding_bytes and artigo_id:
                contexto_vetorial = get_vector_context_for_article(
                    db=db,
                    embedding_bytes=embedding_bytes,
                    artigo_id=artigo_id,
                    days=30,
                    max_results=5,
                )
                
                if contexto_vetorial:
                    contexto_parts.append(f"=== CONTEXTO VETORIAL (artigos semanticamente similares, 30 dias) ===\n{contexto_vetorial}")
                    log.append(f"[Historian] Contexto vetorial: {len(contexto_vetorial)} chars")
                else:
                    log.append("[Historian] Vetorial: nenhum artigo similar encontrado")
            
            # Combina contexto
            contexto_final = "\n\n".join(contexto_parts) if contexto_parts else ""
            
            if contexto_final:
                log.append(f"[Historian] Contexto total: {len(contexto_final)} chars (grafo + vetorial)")
            
            return {
                **state,
                "contexto_historico": contexto_final,
                "embedding_v2": embedding_bytes,
                "processing_log": log,
            }
        finally:
            db.close()
    
    except Exception as e:
        log.append(f"[Historian] Erro: {str(e)[:200]}")
        return {**state, "contexto_historico": "", "processing_log": log}


# ==============================================================================
# NODE 5: WRITER (Resumo com Contexto Historico)
# ==============================================================================

PROMPT_RESUMO_COM_CONTEXTO = """Voce e um Analista Senior da mesa de 'Special Situations' do BTG Pactual.
Escreva um resumo executivo do evento abaixo.

{contexto_historico_section}

TEXTO DA NOTICIA:
{texto}

INSTRUCOES:
- Prioridade do resumo: {prioridade}
  - P1_CRITICO: Resumo longo e detalhado (3-5 paragrafos)
  - P2_ESTRATEGICO: Resumo medio (2-3 paragrafos)
  - P3_MONITORAMENTO: Resumo curto (1-2 frases)
- Se houver CONTEXTO HISTORICO acima, CONECTE o evento atual ao passado.
  Exemplo: "Este e o terceiro atraso consecutivo da empresa esta semana..."
- Foque na tese de investimento e impacto financeiro.
- Nunca invente fatos. Use apenas o que esta no texto.

Responda APENAS com o resumo em texto puro (sem JSON, sem markdown).
"""


def writer_node(state: FeedState) -> FeedState:
    """
    No 5: Gera resumo enriquecido com contexto historico.
    
    ANTES (v1): Prompt recebia apenas {TEXTO_DO_ARTIGO}
    AGORA (v2): Prompt recebe {TEXTO_DO_ARTIGO} + {CONTEXTO_HISTORICO}
    """
    log = state.get("processing_log", [])
    texto = state.get("texto_raw", "")
    titulo = state.get("titulo", "")
    contexto = state.get("contexto_historico", "")
    classificacao = state.get("classificacao", {})
    prioridade = classificacao.get("prioridade", "P3_MONITORAMENTO")
    
    # Monta secao de contexto historico (se existir)
    if contexto:
        contexto_section = f"""CONTEXTO HISTORICO (eventos recentes envolvendo as mesmas entidades):
{contexto}

IMPORTANTE: Conecte o evento atual ao contexto acima quando relevante."""
    else:
        contexto_section = "(Sem contexto historico disponivel para este evento)"
    
    try:
        model = get_gemini_model()
        if not model:
            log.append("[Writer] Gemini indisponivel, usando texto bruto como resumo")
            return {
                **state,
                "resumo_final": texto[:500],
                "resumo_metadata": {"source": "fallback", "has_context": False},
                "processing_log": log,
            }
        
        prompt = PROMPT_RESUMO_COM_CONTEXTO.format(
            contexto_historico_section=contexto_section,
            texto=f"Titulo: {titulo}\n\n{texto[:6000]}",
            prioridade=prioridade,
        )
        
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.3,
                'max_output_tokens': 4096,
            }
        )
        
        resumo = response.text.strip()
        
        log.append(f"[Writer] Resumo gerado ({len(resumo)} chars, contexto: {bool(contexto)})")
        return {
            **state,
            "resumo_final": resumo,
            "resumo_metadata": {
                "source": "llm_with_context" if contexto else "llm_standard",
                "has_context": bool(contexto),
                "prioridade": prioridade,
            },
            "processing_log": log,
        }
    
    except Exception as e:
        log.append(f"[Writer] Erro: {str(e)[:200]}")
        return {
            **state,
            "resumo_final": texto[:500],
            "resumo_metadata": {"source": "error_fallback", "error": str(e)[:100]},
            "processing_log": log,
        }


# ==============================================================================
# EDGE FUNCTIONS (Decisoes condicionais no grafo)
# ==============================================================================

def check_relevance(state: FeedState) -> str:
    """Decide se o artigo e relevante (proximo no) ou irrelevante (END)."""
    if state.get("is_relevant", False):
        return "relevant"
    return "irrelevant"


def check_entities(state: FeedState) -> str:
    """Decide se ha entidades para resolver."""
    if state.get("entities_raw"):
        return "has_entities"
    return "no_entities"
