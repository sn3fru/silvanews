"""
Lógica de processamento em tempo real para o BTG AlphaFeed.
Implementa clusterização dinâmica e análise de notícias.
"""

import os
import json
import numpy as np
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

import google.generativeai as genai
from sqlalchemy.orm import Session

try:
    from .models import Noticia
    from .prompts import PROMPT_EXTRACAO_PERMISSIVO_V8, PROMPT_DECISAO_CLUSTER_DETALHADO_V1, PROMPT_RESUMO_FINAL_V3
    from .utils import (
        extrair_json_da_resposta,
        corrigir_tag_invalida,
        corrigir_prioridade_invalida,
        migrar_noticia_cache_legado,
        get_date_brasil_str,
        normalizar_jornal,
        FONTES_FLASHES,
    )
    from .crud import (
        get_artigo_by_id, update_artigo_processado, update_artigo_status,
        get_active_clusters_today, create_cluster, associate_artigo_to_cluster,
        update_cluster_embedding, create_log, get_artigos_by_cluster, get_cluster_by_id
    )
    from .database import ClusterEvento
except ImportError:
    # Fallback para import absoluto quando executado fora do pacote
    from backend.models import Noticia
    from backend.prompts import PROMPT_EXTRACAO_PERMISSIVO_V8, PROMPT_DECISAO_CLUSTER_DETALHADO_V1, PROMPT_RESUMO_FINAL_V3
    from backend.utils import extrair_json_da_resposta, corrigir_tag_invalida, corrigir_prioridade_invalida, migrar_noticia_cache_legado, get_date_brasil_str, normalizar_jornal, FONTES_FLASHES
    from backend.crud import (
        get_artigo_by_id, update_artigo_processado, update_artigo_status,
        get_active_clusters_today, create_cluster, associate_artigo_to_cluster,
        update_cluster_embedding, create_log, get_artigos_by_cluster, get_cluster_by_id
    )
    from backend.database import ClusterEvento


# ==============================================================================
# EMBEDDINGS SIMPLES (Casca vazia - sem dependências externas)
# ==============================================================================

def gerar_embedding_simples(texto: str) -> bytes:
    """
    Gera um embedding simples baseado no hash do texto.
    Usado como fallback quando sentence-transformers não está disponível.
    
    Args:
        texto: Texto para gerar embedding
        
    Returns:
        Embedding como bytes (384 dimensões para compatibilidade)
    """
    try:
        # Gera hash do texto
        hash_obj = hashlib.md5(texto.encode('utf-8'))
        hash_bytes = hash_obj.digest()
        
        # Cria um vetor de 384 dimensões baseado no hash
        # Usa os bytes do hash para inicializar um array numpy
        np.random.seed(int.from_bytes(hash_bytes[:4], 'big'))
        
        # Gera vetor de 384 dimensões (mesmo tamanho do all-MiniLM-L6-v2)
        embedding = np.random.randn(384).astype(np.float32)
        
        # Normaliza o vetor
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding.tobytes()
        
    except Exception as e:
        print(f"❌ Erro ao gerar embedding simples: {e}")
        # Retorna vetor zero como fallback
        return np.zeros(384, dtype=np.float32).tobytes()


def gerar_embedding(texto: str) -> bytes:
    """
    Converte um texto em um vetor de embedding e retorna como bytes.
    Usa implementação simples sem dependências externas.
    
    Args:
        texto: Texto para gerar embedding
        
    Returns:
        Embedding como bytes para armazenamento no banco (384d)
    """
    try:
        # Usa implementação simples
        return gerar_embedding_simples(texto)
    except Exception as e:
        print(f"❌ Erro ao gerar embedding: {e}")
        return np.zeros(384, dtype=np.float32).tobytes()


def gerar_embedding_v2(texto: str, max_chars: int = 8000) -> Optional[bytes]:
    """
    Gera embedding real de 768 dimensoes via Gemini Embedding API.
    Usado para a coluna embedding_v2 em artigos_brutos (Graph-RAG v2.0).
    
    Modelo: gemini-embedding-001 (3072d nativo, reduzido para 768d via MRL).
    Custo: ~$0.15/1M tokens (gratis no free tier).
    
    Args:
        texto: Texto para gerar embedding
        max_chars: Maximo de caracteres para enviar (Gemini tem limite de ~2048 tokens)
    
    Returns:
        Embedding como bytes (768 floats, np.float32) ou None se falhar.
    """
    import google.generativeai as genai
    import os
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    
    try:
        genai.configure(api_key=api_key)
        
        # Trunca texto para evitar erro de tokens
        texto_truncado = texto[:max_chars].strip()
        if len(texto_truncado) < 10:
            return None
        
        result = genai.embed_content(
            model="models/gemini-embedding-001",
            content=texto_truncado,
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=768,
        )
        
        embedding_list = result.get("embedding") if isinstance(result, dict) else getattr(result, 'embedding', None)
        if not embedding_list:
            return None
        
        embedding_array = np.array(embedding_list, dtype=np.float32)
        
        # Normaliza
        norm = np.linalg.norm(embedding_array)
        if norm > 0:
            embedding_array = embedding_array / norm
        
        return embedding_array.tobytes()
    
    except Exception as e:
        print(f"[Embedding v2] Erro: {e}")
        return None


def cosine_similarity_bytes(a_bytes: bytes, b_bytes: bytes) -> float:
    """Calcula similaridade cosseno entre dois embeddings armazenados como BYTEA."""
    try:
        a = np.frombuffer(a_bytes, dtype=np.float32)
        b = np.frombuffer(b_bytes, dtype=np.float32)
        if len(a) != len(b) or len(a) == 0:
            return 0.0
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    except Exception:
        return 0.0


def verificar_duplicata_semantica(
    db: Session,
    texto: str,
    threshold: float = 0.85,
    horas: int = 48,
    max_candidatos: int = 200,
) -> Optional[Dict[str, Any]]:
    """
    Verifica se ja existe artigo semanticamente similar nas ultimas N horas.
    
    Fluxo:
        1. Gera embedding_v2 (768d Gemini) para o texto candidato.
        2. Busca artigos recentes que possuem embedding_v2.
        3. Calcula similaridade cosseno com cada candidato.
        4. Se max(similaridade) >= threshold, retorna o artigo mais similar.
    
    Args:
        db: Sessao do banco
        texto: Texto do artigo candidato
        threshold: Limiar de similaridade (0-1). Default 0.85.
        horas: Janela temporal em horas. Default 48.
        max_candidatos: Max artigos para comparar. Default 200.
    
    Returns:
        Dict com {artigo_id, titulo, similaridade} se duplicata encontrada, None caso contrario.
    """
    from datetime import timedelta
    try:
        from .database import ArtigoBruto
    except ImportError:
        from backend.database import ArtigoBruto
    
    # 1. Gera embedding do candidato
    emb_candidato = gerar_embedding_v2(texto)
    if emb_candidato is None:
        # Sem embedding = nao conseguimos comparar, permite a insercao
        return None
    
    # 2. Busca artigos recentes com embedding_v2
    from sqlalchemy import and_, func
    corte = datetime.utcnow() - timedelta(hours=horas)
    
    candidatos = db.query(ArtigoBruto.id, ArtigoBruto.titulo_extraido, ArtigoBruto.embedding_v2).filter(
        and_(
            ArtigoBruto.created_at >= corte,
            ArtigoBruto.embedding_v2.isnot(None),
        )
    ).order_by(ArtigoBruto.created_at.desc()).limit(max_candidatos).all()
    
    if not candidatos:
        return None
    
    # 3. Calcula similaridade
    melhor_sim = 0.0
    melhor_artigo = None
    
    for art_id, art_titulo, art_emb in candidatos:
        sim = cosine_similarity_bytes(emb_candidato, art_emb)
        if sim > melhor_sim:
            melhor_sim = sim
            melhor_artigo = (art_id, art_titulo)
    
    # 4. Verifica threshold
    if melhor_sim >= threshold and melhor_artigo:
        return {
            "artigo_id": melhor_artigo[0],
            "titulo": melhor_artigo[1],
            "similaridade": round(melhor_sim, 4),
        }
    
    return None


def bytes_to_embedding(embedding_bytes: bytes) -> np.ndarray:
    """
    Converte bytes de volta para array numpy.
    
    Args:
        embedding_bytes: Embedding como bytes
        
    Returns:
        Array numpy do embedding
    """
    try:
        return np.frombuffer(embedding_bytes, dtype=np.float32)
    except Exception as e:
        print(f"❌ Erro ao converter embedding bytes: {e}")
        return np.array([])


def calcular_similaridade_cosseno(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
    """
    Calcula a similaridade de cosseno entre dois embeddings.
    
    Args:
        embedding1: Primeiro embedding
        embedding2: Segundo embedding
        
    Returns:
        Similaridade de cosseno (0 a 1)
    """
    try:
        # Verifica se os arrays têm o mesmo tamanho
        if embedding1.shape != embedding2.shape:
            print(f"⚠️ Embeddings com tamanhos diferentes: {embedding1.shape} vs {embedding2.shape}")
            return 0.0
        
        # Normaliza os vetores
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        # Calcula a similaridade de cosseno
        similaridade = np.dot(embedding1, embedding2) / (norm1 * norm2)
        return float(similaridade)
    except Exception as e:
        print(f"❌ Erro ao calcular similaridade: {e}")
        return 0.0


# ==============================================================================
# FUNÇÕES DE CLUSTERIZAÇÃO
# ==============================================================================

def find_or_create_cluster(
    db: Session, 
    artigo_analisado: Dict[str, Any], 
    embedding_artigo: bytes,
    client
) -> int:
    """
    Encontra um cluster existente ou cria um novo para o artigo.
    Usa similaridade de embeddings para agrupamento.
    
    Args:
        db: Sessão do banco de dados
        artigo_analisado: Dados do artigo processado
        embedding_artigo: Embedding do artigo
        client: Cliente do Gemini
        
    Returns:
        ID do cluster (existente ou novo)
    """
    try:
        # Busca clusters ativos hoje
        clusters_ativos = get_active_clusters_today(db)
        
        if not clusters_ativos:
            # Cria primeiro cluster do dia
            return _create_new_cluster(db, artigo_analisado, embedding_artigo)
        
        # Converte embedding para array
        embedding_artigo_array = bytes_to_embedding(embedding_artigo)
        
        # Busca cluster mais similar
        melhor_cluster = None
        melhor_similaridade = 0.0
        
        for cluster in clusters_ativos:
            # Verifica se é da mesma tag
            if cluster.tag != artigo_analisado['tag']:
                continue
            
            # Calcula similaridade
            if cluster.embedding_medio:
                embedding_cluster = bytes_to_embedding(cluster.embedding_medio)
                similaridade = calcular_similaridade_cosseno(embedding_artigo_array, embedding_cluster)
                
                if similaridade > melhor_similaridade:
                    melhor_similaridade = similaridade
                    melhor_cluster = cluster
        
        # Se encontrou cluster similar (threshold 0.7)
        if melhor_cluster and melhor_similaridade > 0.7:
            # Consulta LLM para confirmar se deve agrupar
            decisao = _consultar_llm_para_clusterizacao(db, artigo_analisado, melhor_cluster, client)
            
            if decisao.lower() == 'sim':
                # Atualiza embedding médio do cluster
                embeddings = [embedding_artigo_array]
                if melhor_cluster.embedding_medio:
                    embeddings.append(bytes_to_embedding(melhor_cluster.embedding_medio))
                
                embedding_medio = np.mean(embeddings, axis=0)
                update_cluster_embedding(db, melhor_cluster.id, embedding_medio.tobytes())
                
                return melhor_cluster.id
        
        # Cria novo cluster
        return _create_new_cluster(db, artigo_analisado, embedding_artigo)
        
    except Exception as e:
        print(f"❌ Erro ao encontrar/criar cluster: {e}")
        # Fallback: cria novo cluster
        return _create_new_cluster(db, artigo_analisado, embedding_artigo)


def _create_new_cluster(
    db: Session, 
    artigo_analisado: Dict[str, Any], 
    embedding_artigo: bytes
) -> int:
    """
    Cria um novo cluster para o artigo.
    
    Args:
        db: Sessão do banco de dados
        artigo_analisado: Dados do artigo processado
        embedding_artigo: Embedding do artigo
        
    Returns:
        ID do cluster criado
    """
    try:
        try:
            from .models import ClusterEventoCreate
        except ImportError:
            # Fallback para import absoluto quando executado diretamente
            from models import ClusterEventoCreate
        
        cluster_data = ClusterEventoCreate(
            titulo_cluster=artigo_analisado['titulo'],
            resumo_cluster=artigo_analisado['texto_completo'],
            tag=artigo_analisado['tag'],
            prioridade=artigo_analisado['prioridade'],
            embedding_medio=embedding_artigo
        )
        
        cluster = create_cluster(db, cluster_data)
        return cluster.id
        
    except Exception as e:
        print(f"❌ Erro ao criar cluster: {e}")
        return -1


def _consultar_llm_para_clusterizacao(
    db: Session,
    artigo_analisado: Dict[str, Any],
    cluster_existente: ClusterEvento,
    client
) -> str:
    """
    Consulta o LLM para decidir se um artigo pertence a um cluster existente.
    Usa fato_gerador e referente do cluster (Task 7); aviso se mesmo jornal.
    """
    try:
        def _fg_artigo(a) -> str:
            m = getattr(a, "metadados", None) or {}
            fg = m.get("fato_gerador") if isinstance(m, dict) else None
            if isinstance(fg, dict) and fg.get("fato_gerador_padronizado"):
                return (fg.get("fato_gerador_padronizado") or "").strip()
            return (getattr(a, "titulo_extraido", None) or "Sem título")[:120]

        artigos_cluster = get_artigos_by_cluster(db, cluster_existente.id)
        jornais_no_cluster = list({normalizar_jornal(getattr(a, "jornal", None)) for a in artigos_cluster if normalizar_jornal(getattr(a, "jornal", None))})
        # Referente por qualidade (fato_gerador length >= 20)
        MIN_LEN = 20
        artigos_ord = sorted(artigos_cluster, key=lambda a: (getattr(a, "created_at", None) is None, getattr(a, "created_at", None) or datetime.min))
        referente_artigo = None
        for a in artigos_ord:
            if len(_fg_artigo(a)) >= MIN_LEN:
                referente_artigo = a
                break
        if not referente_artigo and artigos_ord:
            referente_artigo = max(artigos_ord, key=lambda a: len(_fg_artigo(a)))
        fato_gerador_referente = _fg_artigo(referente_artigo) if referente_artigo else (cluster_existente.titulo_cluster or "Sem tema")

        jornal_norm = artigo_analisado.get("jornal_normalizado") or normalizar_jornal(artigo_analisado.get("jornal"))
        aviso = ""
        if jornal_norm and jornal_norm in jornais_no_cluster:
            if jornal_norm in (FONTES_FLASHES or []):
                aviso = "\n**CUIDADO (fonte flash):** Esta notícia é do mesmo jornal que já está no cluster. Seja MUITO rigoroso: só responda SIM se for exatamente o mesmo fato (entidade + ação).\n"
            else:
                aviso = "\n**CUIDADO (mesmo jornal):** Esta notícia é do mesmo jornal que já está no cluster. Só responda SIM se for claramente o mesmo evento ou consequência imediata.\n"

        nova_noticia = {
            "titulo": artigo_analisado.get("titulo", ""),
            "jornal": artigo_analisado.get("jornal", ""),
            "fato_gerador": artigo_analisado.get("fato_gerador", (artigo_analisado.get("titulo") or "Sem título")[:120]),
            "trecho": (artigo_analisado.get("texto_completo") or "")[:800],
        }
        cluster_info = {
            "titulo_cluster": cluster_existente.titulo_cluster,
            "fato_gerador_referente": fato_gerador_referente,
            "jornais_no_cluster": jornais_no_cluster,
            "tag": cluster_existente.tag,
        }
        prompt = PROMPT_DECISAO_CLUSTER_DETALHADO_V1.format(
            NOVA_NOTICIA=json.dumps(nova_noticia, ensure_ascii=False, indent=2),
            CLUSTER_EXISTENTE=json.dumps(cluster_info, ensure_ascii=False, indent=2),
            AVISO_MESMO_JORNAL=aviso,
        )
        
        print(f"    🤖 Consultando LLM para clusterização...")
        
        # Usa a API correta do Gemini
        response = client.generate_content(
            prompt,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 512
            }
        )
        
        resposta = response.text.strip().lower()
        print(f"    📥 Resposta do LLM: {resposta}")
        
        # Interpreta a resposta
        if 'sim' in resposta or 'yes' in resposta or 'true' in resposta:
            return 'sim'
        elif 'não' in resposta or 'no' in resposta or 'false' in resposta:
            return 'não'
        else:
            # Se não conseguiu interpretar, assume que não pertence
            print(f"    ⚠️ Resposta ambígua do LLM, assumindo 'não'")
            return 'não'
            
    except Exception as e:
        print(f"    ❌ Erro na consulta LLM: {e}")
        # Em caso de erro, assume que não pertence
        return 'não'


def recalcular_embedding_cluster(db: Session, cluster_id: int) -> bool:
    """
    Recalcula o embedding médio de um cluster baseado nos artigos associados.
    
    Args:
        db: Sessão do banco de dados
        cluster_id: ID do cluster
        
    Returns:
        True se recalculado com sucesso
    """
    try:
        # Busca artigos do cluster
        artigos = get_artigos_by_cluster(db, cluster_id)
        
        if not artigos:
            return False
        
        # Coleta embeddings dos artigos
        embeddings = []
        for artigo in artigos:
            if artigo.embedding:
                embedding_array = bytes_to_embedding(artigo.embedding)
                if len(embedding_array) > 0:
                    embeddings.append(embedding_array)
        
        if not embeddings:
            return False
        
        # Calcula embedding médio
        embedding_medio = np.mean(embeddings, axis=0)
        
        # Atualiza no banco
        return update_cluster_embedding(db, cluster_id, embedding_medio.tobytes())
        
    except Exception as e:
        print(f"❌ Erro ao recalcular embedding do cluster: {e}")
        return False


# ==============================================================================
# PIPELINE PRINCIPAL
# ==============================================================================

def processar_artigo_pipeline(db: Session, id_artigo: int, client) -> bool:
    """
    Pipeline principal de processamento de um artigo.
    Orquestra todo o fluxo desde a análise até a clusterização.
    
    Args:
        db: Sessão do banco de dados
        id_artigo: ID do artigo a ser processado
        client: Cliente do Gemini
        
    Returns:
        True se processado com sucesso, False caso contrário
    """
    try:
        # ETAPA 1: Buscar dados brutos do artigo
        artigo = get_artigo_by_id(db, id_artigo)
        if not artigo:
            create_log(db, "ERROR", "processor", f"Artigo {id_artigo} não encontrado")
            return False
        
        create_log(db, "INFO", "processor", 
                  f"Iniciando processamento do artigo {id_artigo}",
                  {"fonte": artigo.fonte_coleta})
        
        # ETAPA 2: Verificar se já tem metadados estruturados
        metadados = artigo.metadados or {}
        
        # Se já tem dados estruturados (JSON), usa diretamente
        if metadados.get('titulo') and metadados.get('jornal'):
            print(f"    📄 Artigo já estruturado, usando metadados existentes")
            
            noticia_data = {
                'titulo': metadados.get('titulo', 'Sem título'),
                'texto_completo': artigo.texto_bruto,
                'jornal': metadados.get('jornal', 'Fonte desconhecida'),
                'autor': metadados.get('autor', 'N/A'),
                'pagina': metadados.get('pagina'),
                'data': metadados.get('data'),
                'categoria': metadados.get('categoria'),
                'tag': metadados.get('tag', 'Economia e Tecnologia'),
                'prioridade': metadados.get('prioridade', 'P3_MONITORAMENTO')
            }
            
        else:
            # Para PDFs ou artigos sem estrutura, faz extração básica
            print(f"    📄 Artigo sem estrutura, fazendo extração básica")
            
            # Extração básica sem LLM
            linhas = artigo.texto_bruto.split('\n')
            titulo = linhas[0].strip() if linhas else "Sem título"
            
            # Tenta identificar jornal/fonte dos metadados
            jornal = metadados.get('jornal') or metadados.get('fonte_original') or 'Fonte desconhecida'
            
            noticia_data = {
                'titulo': titulo,
                'texto_completo': artigo.texto_bruto,
                'jornal': jornal,
                'autor': metadados.get('autor', 'N/A'),
                'pagina': metadados.get('pagina', '1'),
                'data': metadados.get('data') or get_date_brasil_str(),
                'categoria': metadados.get('categoria', 'Geral'),
                'tag': metadados.get('tag', 'Economia e Tecnologia'),
                'prioridade': metadados.get('prioridade', 'P3_MONITORAMENTO')
            }
        
        # ETAPA 3: Migração e correção de dados
        noticia_data = migrar_noticia_cache_legado(noticia_data)
        
        # Corrige a tag e prioridade se necessário
        if 'tag' in noticia_data:
            noticia_data['tag'] = corrigir_tag_invalida(noticia_data['tag'])
        if 'prioridade' in noticia_data:
            noticia_data['prioridade'] = corrigir_prioridade_invalida(noticia_data['prioridade'])
        
        # ETAPA 4: Validação com Pydantic
        try:
            print(f"    🔍 Validando dados com Pydantic...")
            print(f"    📋 Dados para validação: {noticia_data}")

            noticia_obj = Noticia(**noticia_data)
            noticia_validada = noticia_obj.model_dump()
            # Fato gerador e jornal normalizado para find_or_create_cluster (Task 7)
            fg = (artigo.metadados or {}).get("fato_gerador")
            if isinstance(fg, dict) and fg.get("fato_gerador_padronizado"):
                noticia_validada["fato_gerador"] = (fg.get("fato_gerador_padronizado") or "").strip()
            else:
                noticia_validada["fato_gerador"] = (noticia_validada.get("titulo") or "Sem título")[:120]
            noticia_validada["jornal_normalizado"] = normalizar_jornal(noticia_validada.get("jornal") or "")
            print(f"    ✅ Validação Pydantic bem-sucedida")
        except Exception as e:
            print(f"    ❌ Erro de validação Pydantic: {e}")
            print(f"    📋 Dados que falharam: {noticia_data}")
            create_log(db, "ERROR", "processor", 
                      f"Erro de validação Pydantic do artigo {id_artigo}: {e}")
            update_artigo_status(db, id_artigo, 'erro')
            return False
        
        # ETAPA 5: Gerar embedding
        texto_para_embedding = f"{noticia_validada['titulo']} {noticia_validada['texto_completo']}"
        embedding_artigo = gerar_embedding(texto_para_embedding)
        
        if not embedding_artigo:
            create_log(db, "WARNING", "processor", 
                      f"Falha ao gerar embedding do artigo {id_artigo}")
            embedding_artigo = np.zeros(384, dtype=np.float32).tobytes()
        
        # ETAPA 6: Atualizar artigo com dados processados
        dados_processados = {
            'titulo': noticia_validada['titulo'],
            'texto_completo': noticia_validada['texto_completo'],
            'jornal': noticia_validada['jornal'],
            'autor': noticia_validada['autor'],
            'pagina': noticia_validada['pagina'],
            'data': noticia_validada['data'],
            'categoria': noticia_validada['categoria'],
            'tag': noticia_validada['tag'],
            'prioridade': noticia_validada['prioridade'],
            'relevance_score': noticia_validada.get('relevance_score'),
            'relevance_reason': noticia_validada.get('relevance_reason')
        }
        
        update_artigo_processado(db, id_artigo, dados_processados, embedding_artigo)

        # ETAPA 6.1: Opcional — gerar embedding semântico dedicado (text-embedding-3-small) para busca
        try:
            from btg_alphafeed.semantic_search.embedder import get_default_embedder  # type: ignore
            from btg_alphafeed.semantic_search.store import upsert_embedding_for_artigo  # type: ignore
            emb = get_default_embedder()
            texto_semantico = f"{noticia_validada['titulo']}. {noticia_validada['texto_completo']}"
            vec = emb.embed_text(texto_semantico)
            if isinstance(vec, np.ndarray) and vec.size > 0:
                upsert_embedding_for_artigo(id_artigo, vec, emb.provider, emb.model)
        except Exception as _e_semantic:
            # Não falha o pipeline se indisponível
            pass
        
        # ETAPA 7: Clusterização (aqui sim usa LLM se necessário)
        cluster_id = find_or_create_cluster(db, noticia_validada, embedding_artigo, client)
        
        if cluster_id:
            create_log(db, "INFO", "processor", 
                      f"Artigo {id_artigo} processado e associado ao cluster {cluster_id}")
            return True
        else:
            create_log(db, "ERROR", "processor", 
                      f"Falha na clusterização do artigo {id_artigo}")
            return False
            
    except Exception as e:
        print(f"    ❌ Erro geral no pipeline: {e}")
        import traceback
        traceback.print_exc()
        create_log(db, "ERROR", "processor", 
                  f"Erro geral no pipeline do artigo {id_artigo}: {e}")
        update_artigo_status(db, id_artigo, 'erro')
        return False


def gerar_resumo_cluster(db: Session, cluster_id: int, client) -> bool:
    """
    Gera resumo para um cluster específico.
    
    Args:
        db: Sessão do banco de dados
        cluster_id: ID do cluster
        client: Cliente do Gemini
        
    Returns:
        True se resumo gerado com sucesso
    """
    try:
        # Busca cluster
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            return False
        
        # Busca artigos do cluster
        artigos = get_artigos_by_cluster(db, cluster_id)
        if not artigos:
            return False
        
        # Prepara dados para o prompt
        dados_grupo = []
        for artigo in artigos:
            dados_grupo.append({
                'titulo': artigo.titulo_extraido,
                'jornal': artigo.jornal,
                'pagina': artigo.pagina,
                'prioridade': artigo.prioridade
            })
        
        # Monta o prompt
        prompt = PROMPT_RESUMO_FINAL_V3.format(
            NIVEL_DE_DETALHE=cluster.prioridade,
            DADOS_DO_GRUPO=json.dumps(dados_grupo, ensure_ascii=False)
        )
        
        print(f"    🤖 Gerando resumo para cluster {cluster_id}...")
        
        # Usa a API correta do Gemini
        response = client.generate_content(
            prompt,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 2048
            }
        )
        
        print(f"    📥 Resposta do LLM: {len(response.text)} caracteres")
        
        # Extrai JSON da resposta
        resumo_data = extrair_json_da_resposta(response.text)
        if not resumo_data or not isinstance(resumo_data, dict):
            print(f"    ❌ Falha na extração do JSON do resumo")
            return False
        
        # Atualiza cluster com resumo
        cluster.resumo_cluster = resumo_data.get('resumo_final', '')
        db.commit()
        
        print(f"    ✅ Resumo gerado com sucesso")
        create_log(db, "INFO", "processor", 
                  f"Resumo gerado para cluster {cluster_id}")
        return True
        
    except Exception as e:
        print(f"    ❌ Erro ao gerar resumo do cluster {cluster_id}: {e}")
        create_log(db, "ERROR", "processor", 
                  f"Erro ao gerar resumo do cluster {cluster_id}: {e}")
        return False


def inicializar_processamento():
    """
    Inicializa o sistema de processamento.
    """
    print("✅ Sistema de processamento inicializado com embeddings simples")
    print("💡 Para usar embeddings reais, instale sentence-transformers e configure SSL")