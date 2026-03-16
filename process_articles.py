#!/usr/bin/env python3
"""
Orquestrador para processar artigos pendentes seguindo a lógica do AlphaFeed.
Implementa o fluxo de negócio correto: 
1. Processar todas as notícias (extrair dados raw)
2. Criar clusters/agrupamentos por fato gerador
3. Classificar prioridade e gerar resumos seletivos
"""

import os
import sys
import json
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional
import concurrent.futures

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Configuração SSL para desenvolvimento
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# Imports do backend
try:
    from dotenv import load_dotenv
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
    print("✅ Google Gemini disponível")
except ImportError:
    GEMINI_AVAILABLE = False
    print("❌ AVISO: Google Gemini não está disponível.")
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
from backend.crud import (
    get_artigos_pendentes, create_log, update_artigo_status, 
    update_artigo_processado, update_artigo_dados_sem_status, associate_artigo_to_cluster,
    create_cluster, get_active_clusters_today, get_artigos_by_cluster,
    get_cluster_by_id, update_cluster_priority, update_cluster_tags
)
from backend.models import Noticia, NoticiaResumida, ResumoFinal
from backend.processing import (
    gerar_embedding, bytes_to_embedding, calcular_similaridade_cosseno,
    processar_artigo_pipeline, gerar_resumo_cluster, find_or_create_cluster,
    gerar_embedding_v2, cosine_similarity_bytes,
)
from backend.prompts import PROMPT_AGRUPAMENTO_V1, PROMPT_ANALISE_E_SINTESE_CLUSTER_V1, TAGS_SPECIAL_SITUATIONS
from backend.prompts import _P1_BULLETS, _P2_BULLETS, _P3_BULLETS, GUIA_TAGS_FORMATADO
from backend.prompts import PROMPT_HIGIENIZACAO_V1
from backend.prompts import PROMPT_CONSOLIDACAO_CLUSTERS_V1, TAGS_SPECIAL_SITUATIONS_INTERNACIONAL
from backend.prompts import LISTA_RELEVANCIA_HIERARQUICA_INTERNACIONAL
from backend.utils import (
    get_date_brasil_str,
    get_datetime_brasil_str,
    corrigir_tag_invalida,
    corrigir_prioridade_invalida,
    gerar_titulo_fallback_curto,
    titulo_e_generico,
    normalizar_jornal,
    FONTES_FLASHES,
)
from backend.agents.graph_crud import (
    link_artigo_to_entities,
    get_context_for_cluster,
    get_similar_articles_by_embedding,
)
from backend.agents.nodes import PROMPT_ENTITY_EXTRACTION

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
load_dotenv(env_file)
print(f"SUCESSO: Arquivo .env carregado: {env_file}")

# Configuração de lotes para evitar truncamento
BATCH_SIZE_AGRUPAMENTO = 200  # Lotes maiores para melhor agrupamento (ordenados alfabeticamente antes do envio)
# Etapa 2 (agrupamento): parâmetros adicionais
MAX_OUTPUT_TOKENS_STAGE2 = 32768  # usar o limite alto do modelo para saídas longas
MAX_TRECHO_CHARS_STAGE2 = 120     # reduz trecho por item para poupar contexto

# Configuração do Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERRO: GEMINI_API_KEY não configurada")
    sys.exit(1)

genai.configure(api_key=api_key)
# Etapa 1 (extração) e Etapa 3 (resumos): modelo mais barato
client = genai.GenerativeModel('gemini-2.0-flash')
# Etapa 2 (agrupamento): modelo com mais capacidade de raciocínio para regras estritas
client_agrupamento = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
print("SUCESSO: Gemini configurado (2.0 Flash para extração/resumos; 2.5 Flash para agrupamento).")

# Funções auxiliares para escolher tags/prompts baseado no tipo_fonte
def get_tags_for_tipo_fonte(tipo_fonte: str) -> dict:
    """Retorna as tags apropriadas baseado no tipo de fonte."""
    if tipo_fonte == 'internacional':
        return TAGS_SPECIAL_SITUATIONS_INTERNACIONAL
    return TAGS_SPECIAL_SITUATIONS

def get_prioridades_for_tipo_fonte(tipo_fonte: str) -> list:
    """Retorna as prioridades apropriadas baseado no tipo de fonte."""
    if tipo_fonte == 'internacional':
        return LISTA_RELEVANCIA_HIERARQUICA_INTERNACIONAL
    # Para nacional, retorna None pois usa o sistema atual
    return None

def extrair_json_da_resposta(resposta: str):
    """
    Extrai e repara JSON, retornando (status, dados).
    Status possíveis: SUCESSO, SUCESSO_REPARO, SUCESSO_TRUNCAMENTO,
    RESPOSTA_VAZIA, FALHA_SEM_JSON, FALHA_PARSING_TOTAL.
    """
    import json as _json
    import re as _re

    def _extrair_bloco_json_local(texto: str) -> str:
        m = _re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, _re.DOTALL)
        if m:
            return m.group(1).strip()
        start_pos = texto.find('[')
        if start_pos == -1:
            start_pos = texto.find('{')
        return texto[start_pos:].strip() if start_pos != -1 else ""

    def _sanitizar_json_like_local(json_like: str) -> str:
        s = json_like.replace('```', '')
        s = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
        s = _re.sub(r',\s*([}\]])', r'\1', s)
        def _bal(tx, a, f):
            dif = tx.count(a) - tx.count(f)
            if dif > 0:
                tx += f * dif
            return tx
        s = _bal(s, '[', ']')
        s = _bal(s, '{', '}')
        return s

    if not isinstance(resposta, str) or not resposta.strip():
        return ('RESPOSTA_VAZIA', None)

    bruto = _extrair_bloco_json_local(resposta)
    if not bruto:
        return ('FALHA_SEM_JSON', None)

    try:
        return ('SUCESSO', _json.loads(bruto))
    except _json.JSONDecodeError:
        pass

    reparado = _sanitizar_json_like_local(bruto)
    try:
        return ('SUCESSO_REPARO', _json.loads(reparado))
    except _json.JSONDecodeError:
        pass

    try:
        last_close = max(reparado.rfind('}'), reparado.rfind(']'))
        if last_close != -1:
            truncado = reparado[:last_close + 1]
            if truncado.strip().startswith('[') and truncado.strip().count('[') > truncado.strip().count(']'):
                truncado += ']'
            return ('SUCESSO_TRUNCAMENTO', _json.loads(truncado))
    except _json.JSONDecodeError:
        pass

    return ('FALHA_PARSING_TOTAL', None)

def extrair_json_da_resposta_com_status(resposta: str):
    """
    Extrai e repara JSON, retornando (status, dados).
    Status possíveis: SUCESSO, SUCESSO_REPARO, SUCESSO_TRUNCAMENTO,
    RESPOSTA_VAZIA, FALHA_SEM_JSON, FALHA_PARSING_TOTAL.
    """
    import json as _json
    import re as _re

    def _extrair_bloco_json_local(texto: str) -> str:
        m = _re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, _re.DOTALL)
        if m:
            return m.group(1).strip()
        start_pos = texto.find('[')
        if start_pos == -1:
            start_pos = texto.find('{')
        return texto[start_pos:].strip() if start_pos != -1 else ""

    def _sanitizar_json_like_local(json_like: str) -> str:
        s = json_like.replace('```', '')
        s = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
        # remove vírgulas finais
        s = _re.sub(r',\s*([}\]])', r'\1', s)
        # balanceia colchetes/chaves
        def _bal(tx, a, f):
            dif = tx.count(a) - tx.count(f)
            if dif > 0:
                tx += f * dif
            return tx
        s = _bal(s, '[', ']')
        s = _bal(s, '{', '}')
        return s

    if not isinstance(resposta, str) or not resposta.strip():
        return ('RESPOSTA_VAZIA', None)

    bruto = _extrair_bloco_json_local(resposta)
    if not bruto:
        return ('FALHA_SEM_JSON', None)

    try:
        return ('SUCESSO', _json.loads(bruto))
    except _json.JSONDecodeError:
        pass

    reparado = _sanitizar_json_like_local(bruto)
    try:
        return ('SUCESSO_REPARO', _json.loads(reparado))
    except _json.JSONDecodeError:
        pass

    try:
        last_close = max(reparado.rfind('}'), reparado.rfind(']'))
        if last_close != -1:
            truncado = reparado[:last_close + 1]
            if truncado.strip().startswith('[') and truncado.strip().count('[') > truncado.strip().count(']'):
                truncado += ']'
            return ('SUCESSO_TRUNCAMENTO', _json.loads(truncado))
    except _json.JSONDecodeError:
        pass

    return ('FALHA_PARSING_TOTAL', None)

# ---------------- GATING REMOVIDO - O V13 JÁ FAZ CLASSIFICAÇÃO SUPERIOR -----------------
def _aplicar_gating_explicito_cluster(db: Session, cluster_id: int, debug: bool = True) -> None:
    """
    DESATIVADO - O PROMPT_GATEKEEPER_V13 já faz a classificação correta.
    Mantido apenas para compatibilidade com chamadas existentes.
    """
    if debug:
        print(f"    ℹ️ GATING: Desativado - V13 faz classificação superior")
    return


def _corrigir_tag_deterministica_cluster(db: Session, cluster_id: int, debug: bool = True) -> None:
    """
    Correção determinística de TAG baseada em palavras-chave de alto sinal.
    - Se detectar termos claros de 'Dívida Ativa e Créditos Públicos' (CDA/Certidão de Dívida Ativa, Dívida Ativa,
      securitização de dívida ativa, protesto de CDA, Precatórios, FCVS), força a TAG correspondente.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster or (cluster.tag or "").strip() == 'IRRELEVANTE':
            return
        artigos = get_artigos_by_cluster(db, cluster_id)
        texto_total = " ".join([
            (a.titulo_extraido or "") + " " + (a.texto_processado or "") for a in artigos
        ]) + " " + (cluster.titulo_cluster or "") + " " + (cluster.resumo_cluster or "")

        alvo_divida_ativa = 'Dívida Ativa e Créditos Públicos'
        if (cluster.tag or '').strip() != alvo_divida_ativa:
            padrao_divida_ativa = re.compile(
                r"\b(certid[aã]o\s+de\s+d[ií]vida\s+ativa|\bCDA\b|d[ií]vida\s+ativa|protesto\s+de\s+CDA|securitiza[cç][aã]o\s+de\s+d[ií]vida\s+ativa|precat[óo]ri|\bFCVS\b)\b",
                re.IGNORECASE,
            )
            if padrao_divida_ativa.search(texto_total):
                antigo = (cluster.tag or '').strip()
                cluster.tag = alvo_divida_ativa
                db.commit()
                if debug:
                    print(f"    🏷️ TAG FIX: Cluster {cluster_id} '{antigo}' → '{alvo_divida_ativa}' (sinais fortes: CDA/Dívida Ativa)")
    except Exception as _e:
        if debug:
            print(f"    ⚠️ TAG FIX: Falha ao corrigir tag para cluster {cluster_id}: {_e}")

def corrigir_json_strings(json_str: str) -> str:
    import re
    json_corrigido = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
    json_corrigido = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_corrigido)
    # Escapa quebras de linha não escapadas
    json_corrigido = json_corrigido.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\r')
    # Remove vírgulas finais inválidas
    json_corrigido = re.sub(r',\s*([}\]])', r'\1', json_corrigido)
    return json_corrigido

def extrair_json_valido(json_str: str) -> str:
    """
    Tenta extrair a maior porção inicial de uma string JSON que seja válida.
    Funciona encontrando o último ponto de terminação de um objeto JSON completo
    antes do ponto de truncamento.
    """
    # Procura pelo final do último objeto completo em uma lista.
    # O padrão é: uma chave fechando, seguida opcionalmente por espaços, e uma vírgula.
    # Exemplo: ... {"id": 123}, {"id": 456} <-- queremos parar aqui
    last_good_char_pos = json_str.rfind('},')
    
    if last_good_char_pos != -1:
        # Encontramos um objeto intermediário. Pegamos tudo até ele e fechamos o array.
        # Adicionamos 1 para incluir a chave '}' na fatia.
        partial_json = json_str[:last_good_char_pos + 1]
        
        # Se o JSON original começava com '[', nós fechamos o array com ']'
        if partial_json.strip().startswith('['):
             return partial_json.strip() + ']'
        # Se era um objeto único, apenas retornamos a parte válida
        return partial_json

    # Se não encontrou '},', pode ser um JSON com um único objeto ou já válido.
    # Como fallback, retorna None, pois a extração falhou em encontrar um ponto de corte seguro.
    return None

def extrair_campos_minimos_por_regex(resposta: str) -> Optional[list]:
    """
    Fallback robusto para quando o modelo retorna um JSON malformado.
    Extrai apenas os campos essenciais para o pipeline continuar: 'prioridade' e 'tag'.
    Retorna uma lista com um único dicionário no mesmo formato esperado pela pipeline
    de classificação ou None se não conseguir extrair com confiança.
    """
    try:
        import re
        # 1) Tenta extrair prioridade no formato JSON explícito
        m_prior = re.search(r'"prioridade"\s*:\s*"([^"]+)"', resposta, re.IGNORECASE)
        prioridade = None
        if m_prior:
            prioridade = m_prior.group(1).strip()
        else:
            # 2) Se não houver chave explícita, procura pelos valores canônicos no texto
            prioridades_validas = [
                'P1_CRITICO', 'P2_ESTRATEGICO', 'P3_MONITORAMENTO', 'IRRELEVANTE'
            ]
            for p in prioridades_validas:
                if re.search(rf'\b{re.escape(p)}\b', resposta):
                    prioridade = p
                    break

        # 3) Tenta extrair tag no formato JSON explícito
        m_tag = re.search(r'"tag"\s*:\s*"([^"]+)"', resposta, re.IGNORECASE)
        tag_extraida = m_tag.group(1).strip() if m_tag else None

        # 4) Se não encontrou tag explícita, faz heurística pelas tags conhecidas
        if not tag_extraida:
            try:
                from backend.prompts import TAGS_SPECIAL_SITUATIONS
                tags_canonicas = list(TAGS_SPECIAL_SITUATIONS.keys())
                mapa_lower_para_canonica = {t.lower(): t for t in tags_canonicas}
                # Procura por qualquer citação exata de tag entre aspas
                m_tag_texto = re.search(r'"(M&A e Transações Corporativas|Jurídico, Falências e Regulatório|Dívida Ativa e Créditos Públicos|Distressed Assets e NPLs|Mercado de Capitais e Finanças Corporativas|Política Econômica \(Brasil\)|Internacional \(Economia e Política\)|Tecnologia e Setores Estratégicos|Divulgação de Resultados)"', resposta)
                if m_tag_texto:
                    bruto = m_tag_texto.group(1)
                    tag_extraida = mapa_lower_para_canonica.get(bruto.lower(), bruto)
            except Exception:
                pass

        if not prioridade:
            return None

        # Normaliza prioridade com utilitário do pipeline
        prioridade = corrigir_prioridade_invalida(prioridade)
        if prioridade == 'IRRELEVANTE':
            # Mantém sem tag em caso de irrelevante
            item = {"prioridade": prioridade, "tag": 'IRRELEVANTE'}
            return [item]

        # Se ainda sem tag, aplica fallback seguro
        if not tag_extraida:
            tag_extraida = 'Internacional (Economia e Política)'

        item = {
            "prioridade": prioridade,
            "tag": tag_extraida
        }
        return [item]
    except Exception:
        return None

def extrair_grupos_agrupamento_seguro(resposta: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extrai grupos de agrupamento de forma tolerante a erros para ETAPA 2 (agrupamento em lote).
    1) Tenta via extrair_json_da_resposta (JSON completo válido)
    2) Fallback: usa regex para capturar blocos com "tema_principal" e "ids_originais"
       mesmo se o JSON estiver truncado/quebrado. Deduplica temas e normaliza ids.
    Retorna lista de objetos {"tema_principal": str, "ids_originais": [int, ...]} ou None.
    """
    try:
        status, bruto = extrair_json_da_resposta(resposta)
        if status.startswith('SUCESSO') and isinstance(bruto, list):
            return bruto

        import re
        grupos_map: Dict[str, set] = {}

        padrao = re.compile(
            r"\{\s*\"tema_principal\"\s*:\s*\"(.*?)\"\s*,\s*\"ids_originais\"\s*:\s*\[([\s\S]*?)\]\s*\}",
            re.DOTALL | re.IGNORECASE,
        )
        encontrados = list(padrao.finditer(resposta))

        for m in encontrados:
            tema = (m.group(1) or "").strip()
            ids_str = m.group(2) or ""
            if not tema:
                continue
            # Extrai inteiros da lista, tolerando espaços e vírgulas finais
            ids = []
            for token in re.split(r"[,\s]+", ids_str.strip()):
                if not token:
                    continue
                try:
                    # Remove possíveis sufixos indesejados (e.g., '270]}' em truncamentos)
                    token_limpo = re.sub(r"[^0-9-]", "", token)
                    if token_limpo:
                        ids.append(int(token_limpo))
                except Exception:
                    continue
            if not ids:
                continue
            if tema not in grupos_map:
                grupos_map[tema] = set()
            grupos_map[tema].update(ids)

        # Passo 2: Fallback ainda mais tolerante (tema + ids próximos, mesmo sem colchete de fechamento)
        if not grupos_map:
            try:
                tema_iter = re.finditer(r'"tema_principal"\s*:\s*"([^"]+)"', resposta, re.IGNORECASE)
                for tmatch in tema_iter:
                    tema = (tmatch.group(1) or "").strip()
                    if not tema:
                        continue
                    start = tmatch.end()
                    window = resposta[start:start + 800]
                    ids_m = re.search(r'"ids_originais"\s*:\s*\[([^\]]*)', window, re.IGNORECASE | re.DOTALL)
                    ids = []
                    if ids_m:
                        raw_ids = ids_m.group(1) or ""
                        for token in re.split(r"[,\s]+", raw_ids.strip()):
                            if not token:
                                continue
                            token_limpo = re.sub(r"[^0-9-]", "", token)
                            if token_limpo:
                                try:
                                    ids.append(int(token_limpo))
                                except Exception:
                                    pass
                    if ids:
                        if tema not in grupos_map:
                            grupos_map[tema] = set()
                        grupos_map[tema].update(ids)
            except Exception:
                pass

        if not grupos_map:
            return None

        grupos = [
            {"tema_principal": tema, "ids_originais": sorted(list(ids_set))}
            for tema, ids_set in grupos_map.items()
        ]

        print(f"🔁 Fallback agrupamento: recuperados {len(grupos)} grupos via regex seguro")
        return grupos
    except Exception as e:
        print(f"❌ ERRO: Fallback de extração de grupos falhou: {e}")
        return None

def extrair_classificacoes_incremental_seguro(resposta: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extrai classificações do modo incremental (ETAPA 2 incremental) de forma tolerante a erros.
    Estrutura alvo por item:
      { "tipo": "anexar"|"novo_cluster", "noticia_id": int, "cluster_id_existente"?: int, "tema_principal"?: str }

    1) Tenta via extrair_json_da_resposta.
    2) Fallback: captura blocos com "tipo" usando regex e extrai campos essenciais.
    """
    try:
        status, bruto = extrair_json_da_resposta(resposta)
        if status.startswith('SUCESSO') and isinstance(bruto, list):
            return bruto

        import re

        resultados: List[Dict[str, Any]] = []
        # Captura objetos rasos contendo a chave "tipo"
        obj_pattern = re.compile(r"\{[^{}]*\"tipo\"\s*:\s*\"(anexar|novo_cluster)\"[^{}]*\}", re.IGNORECASE | re.DOTALL)
        for m in obj_pattern.finditer(resposta):
            bloco = m.group(0)

            tipo_m = re.search(r'\"tipo\"\s*:\s*\"(anexar|novo_cluster)\"', bloco, re.IGNORECASE)
            noticia_m = re.search(r'\"noticia_id\"\s*:\s*(\d+)', bloco)
            cluster_m = re.search(r'\"cluster_id_existente\"\s*:\s*(\d+)', bloco)
            tema_m = re.search(r'\"tema_principal\"\s*:\s*\"(.*?)\"', bloco, re.IGNORECASE | re.DOTALL)

            if not tipo_m or not noticia_m:
                continue

            item: Dict[str, Any] = {
                "tipo": tipo_m.group(1).lower(),
                "noticia_id": int(noticia_m.group(1)),
            }
            if cluster_m:
                try:
                    item["cluster_id_existente"] = int(cluster_m.group(1))
                except Exception:
                    pass
            if tema_m:
                item["tema_principal"] = (tema_m.group(1) or "").strip()

            resultados.append(item)

        if resultados:
            print(f"🔁 Fallback incremental: recuperadas {len(resultados)} classificações via regex seguro")
            return resultados
            
        # CORREÇÃO: Fallback mais robusto para objetos truncados
        print("🔁 Tentando fallback mais robusto para objetos truncados...")
        resultados_fallback = []
        
        # Procura por padrões mais simples: tipo + noticia_id
        tipo_pattern = re.compile(r'\"tipo\"\s*:\s*\"(anexar|novo_cluster)\"', re.IGNORECASE)
        noticia_pattern = re.compile(r'\"noticia_id\"\s*:\s*(\d+)')
        tema_pattern = re.compile(r'\"tema_principal\"\s*:\s*\"([^"]+)\"', re.IGNORECASE)
        
        # Divide a resposta em linhas para processar de forma mais robusta
        linhas = resposta.split('\n')
        i = 0
        while i < len(linhas):
            linha = linhas[i]
            
            # Procura por tipo na linha atual
            tipo_match = tipo_pattern.search(linha)
            if tipo_match:
                tipo = tipo_match.group(1).lower()
                
                # Procura noticia_id na mesma linha ou próximas
                noticia_match = noticia_pattern.search(linha)
                if not noticia_match and i + 1 < len(linhas):
                    noticia_match = noticia_pattern.search(linhas[i + 1])
                
                if noticia_match:
                    noticia_id = int(noticia_match.group(1))
                    
                    # Procura tema_principal
                    tema = "Notícias sem título"  # Default
                    for j in range(max(0, i-2), min(len(linhas), i+3)):
                        tema_match = tema_pattern.search(linhas[j])
                        if tema_match:
                            tema = tema_match.group(1).strip()
                            break
                    
                    item = {
                        "tipo": tipo,
                        "noticia_id": noticia_id,
                        "tema_principal": tema
                    }
                    resultados_fallback.append(item)
                    
            i += 1
        
        if resultados_fallback:
            print(f"🔁 Fallback robusto: recuperadas {len(resultados_fallback)} classificações")
            return resultados_fallback
            
        return None
    except Exception as e:
        print(f"❌ ERRO: Fallback incremental falhou: {e}")
        return None


def processar_artigos_pendentes(limite: int = 10, day_str: Optional[str] = None) -> bool:
    """
    Fluxo em estágios com sincronização entre etapas e paralelismo onde seguro:
    1) ETAPA 1 (paralela): processa TODAS as notícias pendentes
    2) ETAPA 2 (síncrona): agrupamento (incremental ou em lote)
    3) ETAPA 3 (paralela): classificar clusters e gerar resumos
    4) ETAPA 4 (síncrona): priorização executiva e consolidação final; re-sumariza se necessário
    """
    # DEBUG: Log da função chamada
    target_day = day_str or get_date_brasil_str()
    print(f"🔧 processar_artigos_pendentes(limite={limite}, day_str={day_str}) → target_day={target_day}")

    db = SessionLocal()
    try:
        # Se uma data específica for fornecida, processa apenas artigos pendentes dessa data
        if day_str:
            artigos_pendentes = db.query(ArtigoBruto).filter(
                ArtigoBruto.status == "pendente",
                func.date(ArtigoBruto.created_at) == day_str
            ).order_by(ArtigoBruto.created_at.asc()).limit(limite).all()
        else:
            artigos_pendentes = get_artigos_pendentes(db, limite=limite)
        if not artigos_pendentes:
            print("✅ Nenhum artigo pendente encontrado")
            return True

        # Estatísticas resumidas
        total_artigos = db.query(ArtigoBruto).count()
        artigos_processados = db.query(ArtigoBruto).filter(ArtigoBruto.status == "processado").count()
        artigos_erro = db.query(ArtigoBruto).filter(ArtigoBruto.status == "erro").count()
        clusters_existentes_count = db.query(ClusterEvento).count()

        print(f"📅 Escopo: apenas dia {target_day} (sem misturar outras datas)")
        print(f"📊 {len(artigos_pendentes)} artigos pendentes | Total no DB: {total_artigos} | Processados: {artigos_processados} | Erros: {artigos_erro} | Clusters: {clusters_existentes_count}")

        # ETAPA 1 — paralela (v2: inclui embedding_v2 + NER + grafo)
        print(f"\n🔄 ETAPA 1: processar_artigo_sem_cluster + Graph-RAG v2 (workers={min(8, max(2, (os.cpu_count() or 4)))})")

        def _worker_proc(id_artigo: int) -> bool:
            _db = SessionLocal()
            try:
                return processar_artigo_sem_cluster(_db, id_artigo, client)
            finally:
                _db.close()

        max_workers = min(8, max(2, (os.cpu_count() or 4)))
        sucessos = 0
        erros = 0
        internacionais = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_worker_proc, art.id): art.id for art in artigos_pendentes}
            for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                try:
                    if fut.result():
                        sucessos += 1
                        # Conta artigos internacionais processados
                        artigo_atual = next((a for a in artigos_pendentes if a.id == futures[fut]), None)
                        if artigo_atual and getattr(artigo_atual, 'tipo_fonte', 'nacional') == 'internacional':
                            internacionais += 1
                    else:
                        erros += 1
                except Exception:
                    erros += 1
                if i % 25 == 0 or i == len(futures):  # Mostra a cada 25 ou no final
                    pct = int((i / len(futures)) * 100)
                    print(f"  📊 {pct}% concluído | ✅ {sucessos} | ❌ {erros} | 🌍 {internacionais}")

        # Estatísticas finais da etapa 1
        taxa_sucesso = (sucessos / len(artigos_pendentes) * 100) if artigos_pendentes else 0
        print(f"✅ ETAPA 1 concluída: {sucessos}/{len(artigos_pendentes)} artigos ({taxa_sucesso:.1f}% sucesso) | 🌍 {internacionais} internacionais")
        if sucessos == 0 and len(artigos_pendentes) > 0:
            print("❌ Nenhum artigo processado com sucesso. Abortando.")
            return False

        # ETAPA 1.5 — Higienização: pré-filtro de ruído (receitas, desporto, fofoca sem ligação corporativa)
        print(f"\n🔄 ETAPA 1.5: Pré-filtro de ruído (higienização)")
        higienizar_lote_artigos(db, client, day_str=target_day)

        # ETAPA 2 — síncrona (v2: inclui dicas de similaridade semantica)
        print(f"\n🔄 ETAPA 2: Agrupamento + dicas v2 (similaridade) - target_day={target_day}")

        clusters_existentes_hoje = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == target_day,
            ClusterEvento.status == 'ativo'
        ).count()

        if clusters_existentes_hoje > 0:
            print(f"🎯 MODO INCREMENTAL: {clusters_existentes_hoje} clusters existentes → agrupar_noticias_incremental()")
            sucesso_agrupamento = agrupar_noticias_incremental(db, client_agrupamento, day_str=target_day)
        else:
            print(f"🎯 MODO EM LOTE: Nenhum cluster existente → agrupar_noticias_com_prompt(day_str={target_day})")
            print(f"📝 Usando prompt: PROMPT_AGRUPAMENTO_V1")
            sucesso_agrupamento = agrupar_noticias_com_prompt(db, client_agrupamento, day_str=target_day)

        if not sucesso_agrupamento:
            print("❌ ETAPA 2 FALHOU: Erro no agrupamento")
            return False
        print("✅ ETAPA 2 concluída: Agrupamento realizado com sucesso")

        # ETAPA 3 — paralela (v2: inclui contexto historico do grafo)
        clusters_hoje = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            func.date(ClusterEvento.created_at) == target_day,
            ClusterEvento.resumo_cluster.is_(None)
        ).all()

        print(f"\n🔄 ETAPA 3: Analise + Sintese + Contexto Grafo v2 - {len(clusters_hoje)} clusters pendentes")
        print(f"📝 Usando prompt: PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 + CONTEXTO_HISTORICO")

        def _worker_classificar_unificado(cid: int) -> bool:
            _db = SessionLocal()
            try:
                # Stats locais por worker não compartilhados (evita race conditions)
                _stats_local = {}
                ok = classificar_e_resumir_cluster(_db, cid, client, _stats_local)
                return bool(ok)
            finally:
                _db.close()

        resultados_etapa3 = {'sucesso': 0, 'falha': 0}
        if clusters_hoje:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(_worker_classificar_unificado, c.id): c.id for c in clusters_hoje}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        if fut.result():
                            resultados_etapa3['sucesso'] += 1
                        else:
                            resultados_etapa3['falha'] += 1
                    except Exception:
                        resultados_etapa3['falha'] += 1

        print(f"✅ ETAPA 3 concluída: Processados {len(clusters_hoje)} clusters.")
        print(f"  - Sucessos: {resultados_etapa3['sucesso']}")
        print(f"  - Falhas: {resultados_etapa3['falha']}")
        if resultados_etapa3['falha'] > 0:
            print("  - Detalhes das falhas foram salvos em 'erros_llm_etapa3.log'")

        # Estatísticas dos clusters criados
        if clusters_hoje:
            try:
                # Histograma de artigos por cluster
                cluster_stats = []
                for c in clusters_hoje:
                    artigos_count = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).count()
                    cluster_stats.append(artigos_count)

                from collections import Counter
                hist = Counter(cluster_stats)
                hist_str = ", ".join([f"{k}art:{v}" for k, v in sorted(hist.items())])
                print(f"📊 Histograma artigos/cluster: {hist_str}")
            except Exception as e:
                print(f"⚠️ Erro ao calcular histograma: {e}")

        # ETAPA 4 — síncrona (v2: inclui similaridade entre clusters via embedding_v2)
        print(f"\n🔄 ETAPA 4: Consolidacao + similaridade v2 (day_str={target_day})")
        print(f"📝 Usando prompt: PROMPT_CONSOLIDACAO_CLUSTERS_V1 + DICAS_SIMILARIDADE")

        ok_cons = consolidacao_final_clusters(SessionLocal(), client, debug=True, day_str=target_day)
        if not ok_cons:
            print("⚠️ ETAPA 4 concluída com avisos")
        else:
            print("✅ ETAPA 4 concluída: Consolidação aplicada")

        # Re-sumariza clusters que ainda ficaram sem resumo após consolidação
        db2 = SessionLocal()
        try:
            hoje = target_day  # Usa o mesmo target_day para consistência
            pendentes = db2.query(ClusterEvento).filter(
                ClusterEvento.status == 'ativo',
                func.date(ClusterEvento.created_at) == hoje,
                ClusterEvento.resumo_cluster.is_(None)
            ).all()
        finally:
            db2.close()

        if pendentes:
            print(f"🔄 Re-sumariando {len(pendentes)} clusters pendentes após consolidação...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(_worker_classificar_unificado, c.id): c.id for c in pendentes}
                for _ in concurrent.futures.as_completed(futures):
                    pass

        # Reconta resumos do dia para estatística final
        try:
            resumos_gerados = db.query(ClusterEvento).filter(
                ClusterEvento.status == 'ativo',
                func.date(ClusterEvento.created_at) == target_day,
                ClusterEvento.resumo_cluster.isnot(None)
            ).count()
        except Exception:
            resumos_gerados = 0

        print(f"\n🎉 PROCESSAMENTO CONCLUÍDO (dia {target_day} — fluxo novo: fato gerador, heurística fonte, referente qualidade, multi-agent gating)")
        print(f"   📈 Artigos processados: {sucessos}")
        print(f"   📝 Resumos gerados: {resumos_gerados}")
        print(f"   🔄 Etapa 4: {'✅ sucesso' if ok_cons else '⚠️ parcial'}")
        return True

    except Exception as e:
        print(f"ERRO: Erro geral no processamento: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

def mapear_tag_prompt_para_modelo(tag_prompt: str, tipo_fonte: str = 'nacional') -> str:
    """
    Normaliza uma tag retornada pelo LLM para uma tag CANÔNICA presente em TAGS_SPECIAL_SITUATIONS.
    - Faz match case-insensitive com as chaves de TAGS_SPECIAL_SITUATIONS.
    - Se não bater, tenta corrigir via corrigir_tag_invalida.
    - Fallback seguro: 'Internacional (Economia e Política)' para nacional, 'Geopolitics and Trade' para internacional.
    """
    try:
        tags_dict = get_tags_for_tipo_fonte(tipo_fonte)
        valid_tags = list(tags_dict.keys())
        
        if not isinstance(tag_prompt, str) or not tag_prompt.strip():
            return 'Geopolitics and Trade' if tipo_fonte == 'internacional' else 'Internacional (Economia e Política)'

        tag_limpa = tag_prompt.strip()

        # Match exato
        if tag_limpa in valid_tags:
            return tag_limpa

        # Match case-insensitive pelas chaves canônicas
        mapa_lower_para_canonica = {t.lower(): t for t in valid_tags}
        if tag_limpa.lower() in mapa_lower_para_canonica:
            return mapa_lower_para_canonica[tag_limpa.lower()]

        # Correção heurística usando utilitário
        tag_corrigida = corrigir_tag_invalida(tag_limpa)
        if tag_corrigida in valid_tags:
            return tag_corrigida
        if tag_corrigida.lower() in mapa_lower_para_canonica:
            return mapa_lower_para_canonica[tag_corrigida.lower()]

        # Fallback
        return 'Geopolitics and Trade' if tipo_fonte == 'internacional' else 'Internacional (Economia e Política)'
    except Exception:
        return 'Geopolitics and Trade' if tipo_fonte == 'internacional' else 'Internacional (Economia e Política)'

def migrar_tag_antiga_para_nova(tag_antiga: str) -> str:
    """
    Migra tags antigas para as novas tags do TAGS_SPECIAL_SITUATIONS.
    """
    mapeamento_antigo = {
        'Economia e Tecnologia': 'Internacional (Economia e Política)',
        'Governo e Politica': 'Política Econômica (Brasil)',
        'Judicionario': 'Jurídico, Falências e Regulatório',
        'Empresas Privadas': 'Mercado de Capitais e Finanças Corporativas'
    }
    
    return mapeamento_antigo.get(tag_antiga, 'Internacional (Economia e Política)')

def marcar_cluster_irrelevante(db: Session, cluster_id: int, debug: bool = True) -> bool:
    """
    Marca um cluster como irrelevante quando o prompt retorna lista vazia.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            return False
        
        # Marca como irrelevante
        cluster.prioridade = "IRRELEVANTE"
        cluster.tag = "IRRELEVANTE"
        cluster.resumo_cluster = "Notícia irrelevante para a mesa de Special Situations"
        
        db.commit()
        
        if debug:
            print(f"    🚫 DEBUG: Cluster {cluster_id} marcado como IRRELEVANTE")
        
        return True
        
    except Exception as e:
        print(f"❌ ERRO: Falha ao marcar cluster {cluster_id} como irrelevante: {e}")
        return False

def classificar_e_resumir_cluster(db: Session, cluster_id: int, client, stats: dict) -> bool:
    """
    Função unificada que classifica, saneia e resume um cluster em uma única chamada de LLM,
    e atualiza o dicionário de estatísticas.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        artigos = get_artigos_by_cluster(db, cluster_id)
        if not cluster or not artigos:
            stats['etapa3_erros_db'] = stats.get('etapa3_erros_db', 0) + 1
            return False

        # 1. Montar o payload com o texto completo de TODOS os artigos
        noticias_payload = []
        for art in artigos:
            noticias_payload.append({
                "id": art.id,
                "titulo": art.titulo_extraido or "Sem título",
                "texto_completo": art.texto_processado or art.texto_bruto or ""
            })

        # 1.5 Multi-Agent Gating: Agente 1 (materialidade) antes do classificador
        bloco_materialidade = ""
        try:
            from backend.prompts import PROMPT_AGENTE_MATERIALIDADE_V1
            payload_agente1 = []
            for art in artigos[:10]:
                fg = (art.metadados or {}).get("fato_gerador") if isinstance(art.metadados, dict) else None
                fato = (fg.get("fato_gerador_padronizado", "")) if isinstance(fg, dict) else ""
                trecho = (art.texto_processado or art.texto_bruto or "")[:400]
                payload_agente1.append({"titulo": art.titulo_extraido or "Sem título", "fato_gerador": fato or "-", "trecho": trecho})
            prompt_ag1 = PROMPT_AGENTE_MATERIALIDADE_V1.strip() + "\n\nDADOS DO CLUSTER:\n" + json.dumps(payload_agente1, ensure_ascii=False, indent=2)
            resp_ag1 = client.generate_content(prompt_ag1, generation_config={"temperature": 0.0, "max_output_tokens": 512})
            status_ag1, dados_ag1 = extrair_json_da_resposta(resp_ag1.text or "")
            if status_ag1.startswith("SUCESSO") and dados_ag1:
                obj_ag1 = dados_ag1[0] if isinstance(dados_ag1, list) and dados_ag1 else dados_ag1
                if isinstance(obj_ag1, dict):
                    deve_p3 = obj_ag1.get("deve_ser_p3", True)
                    just = (obj_ag1.get("justificativa_materialidade") or "").strip() or "Não informado"
                    bloco_materialidade = (
                        "\n\n--- TESTE DE MATERIALIDADE (Agente 1) ---\n"
                        f"Justificativa: {just}\nRecomendação: preferir P3 = {deve_p3}\n"
                        "---\nCom base nisso, classifique prioridade e elabore o resumo. "
                        "Se deve_ser_p3 for true, só atribua P1 ou P2 se houver fato quantitativo ou gatilho explícito (valor em R$, decisão judicial vinculante, default anunciado).\n"
                    )
        except Exception:
            pass

        # 2. Chamar o novo "Super-Prompt" UMA ÚNICA VEZ (com placeholders formais)
        prompt_completo = PROMPT_ANALISE_E_SINTESE_CLUSTER_V1.format(
            NOTICIAS_DO_CLUSTER=json.dumps(noticias_payload, ensure_ascii=False, indent=2),
            P1_BULLETS=_P1_BULLETS,
            P2_BULLETS=_P2_BULLETS,
            P3_BULLETS=_P3_BULLETS,
            GUIA_TAGS_FORMATADO=GUIA_TAGS_FORMATADO
        )
        if bloco_materialidade:
            prompt_completo = bloco_materialidade + prompt_completo

        # Injecao conservadora de regras aprendidas do feedback (Feature 4C)
        try:
            from backend.prompts import get_feedback_rules
            feedback_rules = get_feedback_rules()
            if feedback_rules:
                prompt_completo += f"\n\n--- ADDENDUM: {feedback_rules}\n---"
        except Exception:
            pass

        # v2: Injecao de CONTEXTO HISTORICO do Grafo de Conhecimento
        # Busca eventos recentes envolvendo as mesmas entidades + artigos semanticamente similares
        try:
            contexto_grafo = get_context_for_cluster(db, cluster_id, days_graph=7, days_vector=30)
            if contexto_grafo:
                prompt_completo += (
                    "\n\n--- CONTEXTO HISTORICO (Graph-RAG v2.0) ---\n"
                    "Os seguintes eventos recentes envolvem as mesmas entidades ou sao semanticamente similares.\n"
                    "Se relevante, CONECTE o evento atual ao contexto abaixo no seu resumo.\n"
                    "Exemplo: 'Este e o terceiro anuncio deste tipo nesta semana' ou 'Apos a decisao do STF na semana passada...'.\n"
                    "Se NAO houver conexao relevante, IGNORE esta secao.\n\n"
                    f"{contexto_grafo}\n"
                    "--- FIM DO CONTEXTO HISTORICO ---\n"
                )
        except Exception:
            # PROTECAO: Se get_context_for_cluster falhou com erro SQL,
            # a transacao pode estar corrompida. Rollback limpa a sessao.
            try:
                db.rollback()
            except Exception:
                pass

        response = client.generate_content(prompt_completo, generation_config={'temperature': 0.1, 'top_p': 0.9, 'max_output_tokens': 4096})

        # 3. Parsing com status detalhado
        status, dados = extrair_json_da_resposta(response.text or "")

        # 4. Processar o resultado (espera dict; aceita list[0] como compatibilidade)
        if status.startswith('SUCESSO'):
            if isinstance(dados, list) and len(dados) > 0 and isinstance(dados[0], dict):
                dados = dados[0]
            if not isinstance(dados, dict):
                stats['etapa3_falhas_parsing'] = stats.get('etapa3_falhas_parsing', 0) + 1
                return marcar_cluster_como_erro(db, cluster_id, f"Formato inválido (tipo {type(dados).__name__})")

            stats[f'etapa3_{status.lower()}'] = stats.get(f'etapa3_{status.lower()}', 0) + 1

            obrigatorios = ['prioridade', 'tag', 'resumo_final']
            if not all(k in dados and dados.get(k) for k in obrigatorios):
                stats['etapa3_falhas_parsing'] = stats.get('etapa3_falhas_parsing', 0) + 1
                return marcar_cluster_como_erro(db, cluster_id, "Resposta do LLM sem campos obrigatórios")

            cluster.titulo_cluster = dados.get('titulo', cluster.titulo_cluster)
            cluster.prioridade = corrigir_prioridade_invalida(dados.get('prioridade'))
            tipo_fonte_cluster = getattr(cluster, 'tipo_fonte', 'nacional')
            cluster.tag = mapear_tag_prompt_para_modelo(dados.get('tag'), tipo_fonte_cluster)
            cluster.resumo_cluster = dados.get('resumo_final')
            try:
                db.commit()
            except Exception as commit_err:
                # Commit falhou (encoding, constraint, etc) - rollback e marcar como erro
                print(f"  ⚠️ Commit falhou para cluster {cluster_id}: {str(commit_err)[:120]}")
                try:
                    db.rollback()
                except Exception:
                    pass
                return marcar_cluster_como_erro(db, cluster_id, f"Commit falhou: {str(commit_err)[:150]}")

            # Log opcional de saneamento
            try:
                ids_originais = {a.id for a in artigos}
                ids_usados = set(dados.get('ids_artigos_utilizados', []))
                if ids_usados and ids_originais != ids_usados:
                    with open("log_saneamento_cluster.log", "a", encoding="utf-8") as f:
                        f.write(f"Cluster {cluster_id}: ignorados={sorted(list(ids_originais - ids_usados))} | justificativa={dados.get('justificativa_saneamento')}\n")
            except Exception:
                pass

            _corrigir_tag_deterministica_cluster(db, cluster_id, debug=False)
            return True
        else:
            stats['etapa3_falhas_parsing'] = stats.get('etapa3_falhas_parsing', 0) + 1
            try:
                with open("erros_llm_etapa3.log", "a", encoding="utf-8") as f:
                    f.write(f"--- FALHA CLUSTER ID: {cluster_id} | STATUS: {status} | {datetime.now()} ---\n")
                    f.write("PROMPT ENVIADO (últimos 2000 chars):\n" + (prompt_completo[-2000:] if prompt_completo else "") + "\n\n")
                    f.write("RAW RESPONSE:\n" + (response.text or "NO RESPONSE TEXT") + "\n")
                    f.write("------------------------------------------------------------------\n\n")
            except Exception:
                pass
            return marcar_cluster_como_erro(db, cluster_id, f"Falha na análise: {status}")

    except Exception as e:
        stats['etapa3_erros_execucao'] = stats.get('etapa3_erros_execucao', 0) + 1
        try:
            db.rollback()
        except Exception:
            pass
        return marcar_cluster_como_erro(db, cluster_id, str(e))

def marcar_cluster_como_erro(db: Session, cluster_id: int, motivo: str) -> bool:
    try:
        # CRITICO: Limpa qualquer transacao corrompida antes de operar
        # Isso evita o erro cascata "InFailedSqlTransaction" quando chamado
        # apos um db.commit() que falhou em classificar_e_resumir_cluster
        try:
            db.rollback()
        except Exception:
            pass
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            return False
        cluster.prioridade = "P3_REVISAR"
        cluster.tag = "ERRO"
        cluster.resumo_cluster = f"Falha na classificação automática. Motivo: {motivo[:200]}"
        db.commit()
        print(f"  ⚠️ Cluster {cluster_id} marcado para revisão manual.")
        return True
    except Exception as e:
        print(f"  ❌ Falha ao marcar cluster {cluster_id} como erro: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False

def gerar_resumo_unificado(db: Session, cluster_id: int, client, nivel_detalhe: str) -> bool:
    """
    OBSOLETA: A etapa 3 agora usa PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 para classificar e resumir.
    Mantida apenas por compatibilidade; retorna False para não ser usada.
    """
    return False


def priorizacao_executiva_final(db: Session, client, debug: bool = True) -> bool:
    """
    REMOVIDA - Mantida apenas por compatibilidade com chamadas existentes.
    """
    return True


def consolidacao_final_clusters(db: Session, client, debug: bool = True, day_str: Optional[str] = None) -> bool:
    """
    Etapa 4 (reagrupamento): Consolida clusters redundantes do dia com base em títulos, tags e prioridades já definidas.
    - Prepara uma lista de clusters do dia (exclui IRRELEVANTE e sem prioridade/tag)
    - Envia para o prompt de consolidação pedindo sugestões de merges/keeps
    - Aplica merges conservadores via utilitário de merge no CRUD
    """
    try:
        hoje = day_str or get_date_brasil_str()
        # Seleciona clusters ativos do dia, excluindo irrelevantes
        clusters = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.prioridade != 'IRRELEVANTE',
            ClusterEvento.tag != 'IRRELEVANTE'
        ).all()

        if not clusters:
            if debug:
                print("ℹ️ Consolidação final: nenhum cluster elegível hoje")
            return True

        # Monta payload mínimo por cluster (id, título, tag, prioridade, tipo_fonte)
        itens = []
        for c in clusters:
            itens.append({
                "id": c.id,
                "titulo": c.titulo_cluster,
                "tag": c.tag,
                "prioridade": c.prioridade,
                "tipo_fonte": getattr(c, 'tipo_fonte', 'nacional')
            })

        from backend.crud import merge_clusters, update_cluster_title, update_cluster_priority, update_cluster_tags

        # ---------------------------------------------------------------
        # v2: Calcular similaridade entre clusters via embedding_v2
        # THRESHOLD ALTO (0.92): so sugere merge quando clusters sao quase identicos
        # Threshold baixo (0.75 anterior) gerava falsos positivos ao juntar
        # clusters de temas diferentes mas do mesmo dominio (governo/economia).
        # ---------------------------------------------------------------
        dicas_merge_v2 = ""
        try:
            # Coleta embedding_v2 representativo por cluster (media dos artigos)
            import numpy as np
            cluster_embs = {}  # cluster_id -> embedding_bytes
            for c in clusters:
                artigos_cl = get_artigos_by_cluster(db, c.id)
                embs = [a.embedding_v2 for a in artigos_cl if a.embedding_v2]
                if embs:
                    # Usa a media dos embeddings dos artigos do cluster
                    arrays = [np.frombuffer(e, dtype=np.float32) for e in embs]
                    media = np.mean(arrays, axis=0).astype(np.float32)
                    norm = np.linalg.norm(media)
                    if norm > 0:
                        media = media / norm
                    cluster_embs[c.id] = media.tobytes()
            
            if len(cluster_embs) >= 2:
                pares_merge = []
                ids_com_emb = list(cluster_embs.keys())
                for idx_a in range(len(ids_com_emb)):
                    for idx_b in range(idx_a + 1, len(ids_com_emb)):
                        id_a, id_b = ids_com_emb[idx_a], ids_com_emb[idx_b]
                        sim = cosine_similarity_bytes(cluster_embs[id_a], cluster_embs[id_b])
                        if sim >= 0.92:
                            # Busca titulos
                            titulo_a = next((c.titulo_cluster for c in clusters if c.id == id_a), "?")
                            titulo_b = next((c.titulo_cluster for c in clusters if c.id == id_b), "?")
                            pares_merge.append(
                                f"- Clusters {id_a} e {id_b} tem {sim:.0%} de similaridade semantica"
                            )
                
                if pares_merge:
                    dicas_merge_v2 = (
                        "\n\n--- INFORMACAO ADICIONAL: SIMILARIDADE SEMANTICA (v2) ---\n"
                        "Os clusters abaixo tem alta similaridade semantica (>92%).\n"
                        "ATENCAO: Similaridade semantica NAO significa mesmo fato gerador.\n"
                        "So faca MERGE se os clusters tratam do MESMO EVENTO/FATO concreto.\n"
                        "NAO faca merge apenas porque o tema e parecido (ex: dois assuntos de governo).\n"
                        + "\n".join(pares_merge[:10])
                        + "\n---\n"
                    )
                    if debug:
                        print(f"  [v2] {len(pares_merge)} pares de clusters similares identificados")
        except Exception as e:
            if debug:
                print(f"  [v2] Similaridade de clusters indisponivel: {str(e)[:80]}")

        # ONE-SHOT: tenta enviar todos os clusters de uma vez com max tokens; se falhar, fallback para lotes (código abaixo)
        # Evita KeyError de chaves JSON no format(); substitui placeholder manualmente
        prompt_all = str(PROMPT_CONSOLIDACAO_CLUSTERS_V1).replace(
            '{CLUSTERS_DO_DIA}',
            json.dumps(itens, indent=2, ensure_ascii=False)
        )
        # Injeta dicas de similaridade v2 (sem alterar o template do prompt)
        if dicas_merge_v2:
            prompt_all += dicas_merge_v2
        
        # Injecao conservadora de regras aprendidas do feedback (Feature 4C)
        # Mesma logica usada na Etapa 3, aplicada aqui para consolidacao
        try:
            from backend.prompts import get_feedback_rules
            feedback_rules = get_feedback_rules()
            if feedback_rules:
                prompt_all += f"\n\n--- ADDENDUM (FEEDBACK DOS ANALISTAS): {feedback_rules}\n---"
        except Exception:
            pass
        
        if debug:
            print(f"🧩 Consolidação one-shot: enviando {len(itens)} clusters")
        try:
            resp_all = client.generate_content(
                prompt_all,
                generation_config={'temperature': 0.1, 'top_p': 0.8, 'max_output_tokens': 32768}
            )
        except Exception as e:
            if debug:
                print(f"❌ Consolidação one-shot falhou na chamada: {e}")
            resp_all = None

        merges_aplicados_total = 0
        keeps_total = 0
        if resp_all and resp_all.text:
            sugestoes_all = extrair_sugestoes_consolidacao_seguro(resp_all.text)
            if isinstance(sugestoes_all, list) and len(sugestoes_all) > 0:
                destinos_reprocessar = set()
                for s in sugestoes_all:
                    try:
                        if not isinstance(s, dict):
                            continue
                        tipo = (s.get('tipo') or '').lower()
                        if tipo == 'keep' and s.get('cluster_id'):
                            keeps_total += 1
                            continue
                        if tipo == 'merge':
                            destino = s.get('destino')
                            fontes = s.get('fontes') or []
                            novo_titulo = s.get('novo_titulo')
                            nova_tag = s.get('nova_tag')
                            nova_prioridade = s.get('nova_prioridade')
                            if not destino or not fontes:
                                continue
                            # Proteção: não consolidar em destino com título genérico
                            try:
                                destino_obj = db.query(ClusterEvento).filter(ClusterEvento.id == int(destino)).first()
                                if destino_obj and titulo_e_generico(destino_obj.titulo_cluster):
                                    continue
                            except Exception:
                                pass
                            
                            # CORREÇÃO: Verifica se os clusters têm tipos_fonte compatíveis
                            try:
                                fonte_objs = [db.query(ClusterEvento).filter(ClusterEvento.id == int(fid)).first() for fid in fontes]
                                fonte_objs = [f for f in fonte_objs if f is not None]
                                if destino_obj and fonte_objs:
                                    tipo_destino = getattr(destino_obj, 'tipo_fonte', 'nacional') or 'nacional'
                                    tipos_fontes = [getattr(f, 'tipo_fonte', 'nacional') or 'nacional' for f in fonte_objs]
                                    # Bloqueia qualquer mistura entre internacional e brasil_* (inclui legado 'nacional')
                                    misturando_internacional = (
                                        (tipo_destino == 'internacional' and any(tf != 'internacional' for tf in tipos_fontes)) or
                                        (tipo_destino != 'internacional' and any(tf == 'internacional' for tf in tipos_fontes))
                                    )
                                    if misturando_internacional:
                                        continue
                            except Exception:
                                pass
                            
                            # NÃO passa tag/prioridade - deixa a Etapa 3 decidir
                            merge_clusters(
                                db,
                                destino_id=int(destino),
                                fontes_ids=[int(x) for x in fontes if isinstance(x, (int, str))],
                                novo_titulo=novo_titulo,
                                nova_tag=None,  # Etapa 3 decide
                                nova_prioridade=None,  # Etapa 3 decide
                                motivo='consolidação etapa 4'
                            )
                            merges_aplicados_total += 1
                            destinos_reprocessar.add(int(destino))
                            # Recalcula tipo_fonte do destino usando precedência (internacional > brasil_fisico > brasil_online)
                            try:
                                artigos_dest = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == int(destino)).all()
                                tipos_dest = [(getattr(a, 'tipo_fonte', None) or '').strip().lower() for a in artigos_dest]
                                if any(t == 'internacional' for t in tipos_dest):
                                    destino_obj.tipo_fonte = 'internacional'
                                elif any(t in ('brasil_fisico', 'nacional') for t in tipos_dest):
                                    destino_obj.tipo_fonte = 'brasil_fisico'
                                elif any(t == 'brasil_online' for t in tipos_dest):
                                    destino_obj.tipo_fonte = 'brasil_online'
                                db.commit()
                            except Exception as commit_err:
                                # Rollback para nao envenenar a sessao para proximas iteracoes
                                try:
                                    db.rollback()
                                except Exception:
                                    pass
                    except Exception:
                        # Rollback para garantir sessao limpa na proxima iteracao
                        try:
                            db.rollback()
                        except Exception:
                            pass
                        continue
                if debug:
                    print(f"✅ Consolidação final (one-shot) aplicada. merges={merges_aplicados_total}, keeps={keeps_total}")
                # Reprocessa (Etapa 3) os clusters destino para atualizar resumo/tag/prioridade
                # Usa sessao fresca por cluster para evitar contaminacao cruzada
                for cid in destinos_reprocessar:
                    _reprocess_db = SessionLocal()
                    try:
                        _ = classificar_e_resumir_cluster(_reprocess_db, cid, client, stats={})
                    except Exception:
                        pass
                    finally:
                        _reprocess_db.close()
                return True

        # One-shot não produziu sugestões: aplica fallback estrito por título/tag em TODOS os itens
        if debug:
            print("ℹ️ Consolidação: sem sugestões — aplicando fallback estrito por título/tag (one-shot)")
        try:
            import unicodedata, re as _re
            def _norm(t: str) -> str:
                if not isinstance(t, str):
                    return ''
                t = unicodedata.normalize('NFKD', t)
                t = ''.join(c for c in t if not unicodedata.combining(c))
                t = t.lower()
                t = _re.sub(r"[^a-z0-9]+", " ", t).strip()
                return t
            grupos = {}
            for it in itens:
                titulo_norm = _norm(it.get('titulo') or '')
                # Evita agrupar por títulos genéricos (ex.: 'sem titulo')
                if not titulo_norm or titulo_e_generico(it.get('titulo')):
                    continue
                # Inclui tipo_fonte na chave para evitar merges entre tipos diferentes
                chave = (titulo_norm, it.get('tag'), it.get('tipo_fonte'))
                if not chave[0] or not chave[1]:
                    continue
                grupos.setdefault(chave, []).append(it)
            merges_aplicados_fallback = 0
            for (_, _tag), items in grupos.items():
                if len(items) <= 1:
                    continue
                destino_id = min(i['id'] for i in items)
                fontes_ids = [i['id'] for i in items if i['id'] != destino_id]
                from backend.crud import merge_clusters as _merge
                _merge(db, destino_id=destino_id, fontes_ids=fontes_ids, motivo='fallback titulo/tag etapa 4')
                merges_aplicados_fallback += 1
            if debug:
                print(f"   ↪ fallback merges aplicados: {merges_aplicados_fallback}")
        except Exception as _e:
            if debug:
                print(f"   ⚠️ Fallback estrito falhou: {_e}")

        if debug:
            print(f"✅ Consolidação por sugestões aplicada. merges={merges_aplicados_total}, keeps={keeps_total}")

        # Passo final: Fallback determinístico SEM modelo para captar quase-duplicatas remanescentes
        try:
            if debug:
                print("🔁 Consolidação determinística por título/tag (pós-sugestões)...")
            # Recarrega clusters atuais do dia
            hoje2 = day_str or get_date_brasil_str()
            clusters2 = db.query(ClusterEvento).filter(
                ClusterEvento.status == 'ativo',
                func.date(ClusterEvento.created_at) == hoje2,
                ClusterEvento.prioridade != 'IRRELEVANTE',
                ClusterEvento.tag != 'IRRELEVANTE'
            ).all()

            # Prepara normalização de título
            import unicodedata, re as _re
            def _norm_tokens(t: str) -> List[str]:
                if not isinstance(t, str):
                    return []
                t0 = unicodedata.normalize('NFKD', t)
                t0 = ''.join(c for c in t0 if not unicodedata.combining(c))
                t0 = t0.lower()
                t0 = _re.sub(r"[^a-z0-9\s]", " ", t0).strip()
                tokens = [tok for tok in t0.split() if len(tok) > 2]
                return tokens

            def _jaccard(a: List[str], b: List[str]) -> float:
                if not a or not b:
                    return 0.0
                sa, sb = set(a), set(b)
                inter = len(sa & sb)
                uni = len(sa | sb)
                return (inter / uni) if uni else 0.0

            # Índice por tag
            tag_to_items: Dict[str, List[Dict[str, Any]]] = {}
            for c in clusters2:
                toks = _norm_tokens(c.titulo_cluster or "")
                if not toks:
                    continue
                tag_to_items.setdefault(c.tag or '', []).append({
                    'id': c.id,
                    'tokens': toks,
                    'prio': c.prioridade or 'P3_MONITORAMENTO',
                    'tipo_fonte': getattr(c, 'tipo_fonte', 'nacional')  # CORREÇÃO: Preserva tipo_fonte
                })

            # Gera grupos por tag usando união por similaridade de Jaccard
            from collections import defaultdict
            merges_deterministic = 0
            for tag, items in tag_to_items.items():
                n = len(items)
                if n <= 1:
                    continue
                parent = list(range(n))
                def find(x: int) -> int:
                    while parent[x] != x:
                        parent[x] = parent[parent[x]]
                        x = parent[x]
                    return x
                def union(x: int, y: int) -> None:
                    rx, ry = find(x), find(y)
                    if rx != ry:
                        parent[ry] = rx

                # Só aplica para P3 por segurança; evita merges agressivos em P1/P2
                idxs = [i for i, it in enumerate(items) if it['prio'] == 'P3_MONITORAMENTO']
                for i in range(len(idxs)):
                    for j in range(i + 1, len(idxs)):
                        a, b = items[idxs[i]], items[idxs[j]]
                        # CORREÇÃO: Só permite merge se os tipos_fonte forem compatíveis
                        if a['tipo_fonte'] != b['tipo_fonte']:
                            continue
                        jac = _jaccard(a['tokens'], b['tokens'])
                        if jac >= 0.85:
                            union(idxs[i], idxs[j])

                comps: Dict[int, List[int]] = defaultdict(list)
                for i in range(n):
                    comps[find(i)].append(i)

                for comp in comps.values():
                    # filtra apenas componentes com mais de 1 P3
                    comp_p3 = [k for k in comp if items[k]['prio'] == 'P3_MONITORAMENTO']
                    if len(comp_p3) <= 1:
                        continue
                    destino = min(items[k]['id'] for k in comp_p3)
                    fontes = [items[k]['id'] for k in comp_p3 if items[k]['id'] != destino]
                    if not fontes:
                        continue
                    try:
                        from backend.crud import merge_clusters as _merge
                        _merge(db, destino_id=destino, fontes_ids=fontes, motivo='fallback deterministico titulo/tag etapa 4 (P3)')
                        merges_deterministic += 1
                    except Exception:
                        continue

            if debug:
                print(f"✅ Consolidação determinística aplicada. merges={merges_deterministic}")
        except Exception as _e:
            if debug:
                print(f"⚠️ Consolidação determinística falhou: {_e}")

        return True

    except Exception as e:
        print(f"❌ ERRO: Consolidação final falhou: {e}")
        return False


def corigir_prioridade(valor: Optional[str]) -> Optional[str]:
    try:
        if not valor:
            return None
        return corrigir_prioridade_invalida(valor)
    except Exception:
        return None


def extrair_sugestoes_consolidacao_seguro(resposta: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extrai sugestões da etapa 4 de forma robusta:
      1) Tenta parse JSON direto via extrair_json_da_resposta
      2) Fallback: regex para objetos com campos essenciais (tipo, destino/fontes/cluster_id)
    Retorna lista de dicts padronizados: {tipo, destino?, fontes?, cluster_id?, novo_titulo?, nova_tag?, nova_prioridade?}
    """
    try:
        # Limpeza leve de marcas comuns
        resposta = resposta.replace('\u200b', '').replace("\ufeff", '')
        status, bruto = extrair_json_da_resposta(resposta)
        itens: List[Dict[str, Any]] = []
        if status.startswith('SUCESSO') and isinstance(bruto, list):
            for obj in bruto:
                if isinstance(obj, dict) and ('tipo' in obj):
                    itens.append(obj)
        if itens:
            return itens

        # Fallback por regex
        import re
        # Captura blocos que claramente pertencem à estrutura, tolerando quebras de linha e backticks
        candidatos = re.findall(r"\{[\s\S]*?\}", resposta)
        resultados: List[Dict[str, Any]] = []
        for cand in candidatos:
            try:
                texto = cand
                # Normaliza aspas/backticks
                texto = texto.replace('```', '').replace("\n", " ").replace("\r", " ")
                # Extrai campos
                tipo_m = re.search(r'"tipo"\s*:\s*"(merge|keep)"', texto, re.IGNORECASE)
                if not tipo_m:
                    continue
                item: Dict[str, Any] = {"tipo": tipo_m.group(1).lower()}
                dest_m = re.search(r'"destino"\s*:\s*(\d+)', texto)
                fontes_m = re.search(r'"fontes"\s*:\s*\[([^\]]*)\]', texto, re.DOTALL)
                keep_m = re.search(r'"cluster_id"\s*:\s*(\d+)', texto)
                nt_m = re.search(r'"novo_titulo"\s*:\s*"(.*?)"', texto, re.DOTALL)
                tag_m = re.search(r'"nova_tag"\s*:\s*"(.*?)"', texto, re.DOTALL)
                pr_m = re.search(r'"nova_prioridade"\s*:\s*"(P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO)"', texto)

                if (item.get('tipo') or '').lower() == 'merge':
                    if dest_m:
                        item['destino'] = int(dest_m.group(1))
                    fontes = []
                    if fontes_m:
                        for t in re.split(r"[,\s]+", (fontes_m.group(1) or '').strip()):
                            if not t:
                                continue
                            tnum = re.sub(r"[^0-9]", "", t)
                            if tnum:
                                try:
                                    fontes.append(int(tnum))
                                except Exception:
                                    pass
                    if fontes:
                        item['fontes'] = fontes
                    if nt_m:
                        item['novo_titulo'] = nt_m.group(1).strip()
                    if tag_m:
                        item['nova_tag'] = tag_m.group(1).strip()
                    if pr_m:
                        item['nova_prioridade'] = pr_m.group(1).strip()
                else:
                    if keep_m:
                        item['cluster_id'] = int(keep_m.group(1))

                # Valida mínimos
                if (item.get('tipo') or '').lower() == 'merge' and (not item.get('destino') or not item.get('fontes')):
                    continue
                resultados.append(item)
            except Exception:
                continue
        return resultados
    except Exception:
        return None


def extrair_priorizacao_executiva_seguro(resposta: str) -> Optional[List[Dict[str, Any]]]:
    """
    Fallback robusto para a priorização executiva: extrai uma lista de itens com
    campos chaves (id, decisao_prioridade_final, tag_final opcional) mesmo que o JSON venha truncado.
    """
    try:
        import re
        objetos = re.findall(r"\{[\s\S]*?\}", resposta)
        resultados: List[Dict[str, Any]] = []
        for obj in objetos:
            try:
                rid_m = re.search(r'"id"\s*:\s*(\d+)', obj)
                dec_m = re.search(r'"decisao_prioridade_final"\s*:\s*"(P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO|IRRELEVANTE)"', obj)
                tag_m = re.search(r'"tag_final"\s*:\s*"(.*?)"', obj)
                if not rid_m or not dec_m:
                    continue
                item = {
                    "id": int(rid_m.group(1)),
                    "decisao_prioridade_final": dec_m.group(1)
                }
                if tag_m:
                    item["tag_final"] = tag_m.group(1)
                resultados.append(item)
            except Exception:
                continue
        return resultados
    except Exception:
        return None


def higienizar_lote_artigos(db: Session, client, day_str: Optional[str] = None) -> int:
    """
    Etapa 1.5: Pré-filtro de rejeição. Marca como 'irrelevante' quando o FOCO CENTRAL do texto
    é culinária, astrologia, desporto, entretenimento/fofoca, vida pessoal ou previsão do tempo.
    Mera menção a "empresa"/"banco" no meio de texto de fofoca/desporto NÃO torna o artigo relevante.
    Retorna o número de artigos marcados como irrelevantes (não entram na Etapa 2).
    """
    target_day = day_str or get_date_brasil_str()
    query = db.query(ArtigoBruto).filter(
        ArtigoBruto.status == "pronto_agrupar",
        ArtigoBruto.cluster_id.is_(None),
        func.date(ArtigoBruto.created_at) == target_day,
    )
    artigos = query.order_by(ArtigoBruto.id.asc()).all()
    if not artigos:
        return 0
    BATCH_HIGIEN = 20
    total_irrelevantes = 0
    for inicio in range(0, len(artigos), BATCH_HIGIEN):
        lote = artigos[inicio:inicio + BATCH_HIGIEN]
        payload = []
        for i, art in enumerate(lote):
            titulo = (art.titulo_extraido or "Sem título")[:200]
            trecho = (art.texto_processado or art.texto_bruto or "")[:1500]
            payload.append({"id": i, "titulo": titulo, "trecho": trecho[:800]})
        texto_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        prompt_completo = PROMPT_HIGIENIZACAO_V1.strip() + "\n\nARTIGOS:\n" + texto_payload
        try:
            resp = client.generate_content(
                prompt_completo,
                generation_config={"temperature": 0.0, "max_output_tokens": 1024},
            )
            status_json, raw = extrair_json_da_resposta(resp.text or "")
            if not status_json.startswith("SUCESSO") or not raw:
                continue
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict) and item.get("is_lixo") is True:
                        idx = item.get("id", 0)
                        if 0 <= idx < len(lote):
                            art = lote[idx]
                            update_artigo_status(db, art.id, "irrelevante")
                            total_irrelevantes += 1
        except Exception as e:
            print(f"  ⚠️ Higienização lote {inicio//BATCH_HIGIEN + 1}: {e}")
        db.commit()
    if total_irrelevantes:
        print(f"🧹 ETAPA 1.5: {total_irrelevantes} artigos marcados como irrelevantes (não entram na Etapa 2)")
    return total_irrelevantes


def agrupar_noticias_incremental(db: Session, client, day_str: Optional[str] = None) -> bool:
    """
    Agrupamento incremental: anexa novas notícias a clusters existentes ou cria novos clusters.
    Usa o prompt PROMPT_AGRUPAMENTO_INCREMENTAL_V1 para decisão inteligente.
    Processa em lotes se houver muitas notícias para evitar truncamento.
    """
    try:
        # Busca artigos prontos para agrupamento que não foram associados a clusters
        target_day = day_str or get_date_brasil_str()
        query = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.is_(None)  # Artigos não associados a clusters
        )
        
        # Se uma data específica for fornecida, filtra por ela
        if day_str:
            query = query.filter(func.date(ArtigoBruto.created_at) == day_str)
        
        artigos_novos = query.all()
        
        if not artigos_novos:
            print("INFO: Nenhum artigo novo encontrado para agrupamento incremental")
            return True
        
        # Busca clusters existentes da data alvo
        clusters_existentes = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == target_day,
            ClusterEvento.status == 'ativo'
        ).all()
        
        print(f"🔗 AGRUPAMENTO INCREMENTAL (apenas dia {target_day} — sem misturar outras datas)")
        print(f"   📰 Notícias novas: {len(artigos_novos)} | Clusters existentes do dia: {len(clusters_existentes)}")

        # SEPARAÇÃO POR TRÊS TIPOS: Brasil Físico, Brasil Online, Internacional
        def _get_tipo_fonte_normalizado(obj):
            """Normaliza tipo_fonte para garantir compatibilidade"""
            tipo = getattr(obj, 'tipo_fonte', 'brasil_fisico')
            # Retrocompatibilidade com sistema antigo
            if tipo == 'nacional':
                return 'brasil_fisico'  # Default para PDFs
            elif tipo in ('brasil_fisico', 'brasil_online', 'internacional'):
                return tipo
            else:
                return 'brasil_fisico'  # Default seguro
        
        # Separação mais granular
        artigos_brasil_fisico = [a for a in artigos_novos if _get_tipo_fonte_normalizado(a) == 'brasil_fisico']
        artigos_brasil_online = [a for a in artigos_novos if _get_tipo_fonte_normalizado(a) == 'brasil_online']
        artigos_internacional = [a for a in artigos_novos if _get_tipo_fonte_normalizado(a) == 'internacional']
        
        clusters_brasil_fisico = [c for c in clusters_existentes if _get_tipo_fonte_normalizado(c) == 'brasil_fisico']
        clusters_brasil_online = [c for c in clusters_existentes if _get_tipo_fonte_normalizado(c) == 'brasil_online']
        clusters_internacional = [c for c in clusters_existentes if _get_tipo_fonte_normalizado(c) == 'internacional']
        
        # Isolamento estrito: cada tipo_fonte é processado separadamente (sem misturar brasil_fisico com brasil_online)
        print(f"   📊 Por tipo: artigos {len(artigos_brasil_fisico)} físicos, {len(artigos_brasil_online)} online, {len(artigos_internacional)} int. | clusters {len(clusters_brasil_fisico)} fís., {len(clusters_brasil_online)} onl., {len(clusters_internacional)} int.")
        
        TAMANHO_LOTE_MAXIMO = 100  # Reduzido para evitar truncamento de respostas do modelo
        def _processar_por_tipo(nome: str, artigos_lista, clusters_lista, numero_bloco_base: int = 1) -> tuple:
            if not artigos_lista:
                return (0, 0)
            print(f"📦 Incremental ({nome}): {len(artigos_lista)} notícias | clusters compatíveis: {len(clusters_lista)}")
            _processar_em_lotes = len(artigos_lista) > TAMANHO_LOTE_MAXIMO
            if _processar_em_lotes:
                print(f"📦 Lotes: {len(artigos_lista)} notícias em blocos de {TAMANHO_LOTE_MAXIMO}")
                lotes = [artigos_lista[i:i + TAMANHO_LOTE_MAXIMO] for i in range(0, len(artigos_lista), TAMANHO_LOTE_MAXIMO)]
                total_anex, total_novos = 0, 0
                for i, lote in enumerate(lotes, numero_bloco_base):
                    r = processar_lote_incremental(db, client, lote, clusters_lista, i)
                    if r:
                        a, n = r
                        total_anex += a
                        total_novos += n
                        print(f"✅ Lote {nome} {i}: {a} anexações, {n} novos clusters")
                    else:
                        print(f"❌ Lote {nome} {i} falhou")
                        return (0, 0)
                return (total_anex, total_novos)
            else:
                r = processar_lote_incremental(db, client, artigos_lista, clusters_lista, numero_bloco_base)
                return r if r else (0, 0)

        anex_f, novos_f = _processar_por_tipo('BRASIL_FISICO', artigos_brasil_fisico, clusters_brasil_fisico, 1)
        anex_o, novos_o = _processar_por_tipo('BRASIL_ONLINE', artigos_brasil_online, clusters_brasil_online, 1)
        anex_int, novos_int = _processar_por_tipo('INTERNACIONAL', artigos_internacional, clusters_internacional, 1)
        anex_total = anex_f + anex_o + anex_int
        novos_total = novos_f + novos_o + novos_int
        
        # Marca artigos como "processado" após clusterização
        marcar_artigos_processados(db, artigos_novos)
        
        print(f"🎉 Incremental concluído: {anex_total} anexações, {novos_total} novos clusters")
        return True
        
    except Exception as e:
        print(f"❌ ERRO: Falha no agrupamento incremental: {e}")
        import traceback
        traceback.print_exc()
        return False

def marcar_artigos_processados(db: Session, artigos: List[ArtigoBruto]) -> None:
    """
    Marca artigos como "processado" após clusterização bem-sucedida.
    """
    try:
        for artigo in artigos:
            artigo.status = "processado"
            artigo.processed_at = get_datetime_brasil_str()
        
        db.commit()
        print(f"✅ {len(artigos)} artigos marcados como 'processado' após clusterização")
        
    except Exception as e:
        print(f"❌ ERRO: Falha ao marcar artigos como processado: {e}")
        db.rollback()

def processar_lote_incremental(db: Session, client, artigos_lote: List[ArtigoBruto], clusters_existentes: List[ClusterEvento], numero_lote: int = 1) -> tuple:
    """
    Processa um lote de artigos no agrupamento incremental.
    Retorna (anexacoes, novos_clusters) ou False se falhar.
    Exige que todos os artigos do lote tenham o mesmo tipo_fonte; caso contrário lança exceção.
    """
    try:
        # Isolamento estrito por tipo_fonte: lote não pode misturar brasil_fisico com brasil_online ou internacional
        if artigos_lote:
            def _tipo(a):
                t = getattr(a, 'tipo_fonte', None) or 'brasil_fisico'
                return 'brasil_fisico' if t == 'nacional' else t
            tipos_no_lote = {_tipo(a) for a in artigos_lote}
            if len(tipos_no_lote) > 1:
                raise ValueError(
                    f"Lote {numero_lote} mistura tipo_fonte: {tipos_no_lote}. "
                    "Cada lote deve ter um único tipo_fonte (brasil_fisico, brasil_online ou internacional)."
                )
        # Flag local para logs opcionais neste escopo (evita NameError em 'if debug')
        debug = False
        # Prepara dados para o prompt incremental
        def _fato_gerador_artigo(a: ArtigoBruto) -> str:
            m = (a.metadados or {}) or {}
            fg = m.get("fato_gerador")
            if isinstance(fg, dict) and fg.get("fato_gerador_padronizado"):
                return (fg.get("fato_gerador_padronizado") or "").strip()
            return (a.titulo_extraido or "Sem título")[:120]

        # Excluir artigos sem fato gerador válido (evitar clusters "N/A - N/A")
        artigos_lote_validos = []
        for artigo in artigos_lote:
            fg = _fato_gerador_artigo(artigo)
            if not fg or not fg.strip() or fg.strip().upper() in ("N/A", "SEM TÍTULO", "SEM TITULO") or len(fg.strip()) < 5:
                metadados_art = dict(artigo.metadados or {})
                metadados_art["fato_gerador_erro"] = True
                artigo.metadados = metadados_art
                update_artigo_status(db, artigo.id, "erro")
                db.commit()
                continue
            artigos_lote_validos.append(artigo)
        artigos_lote = artigos_lote_validos
        if not artigos_lote:
            return (0, 0)

        novas_noticias = []
        for i, artigo in enumerate(artigos_lote):
            noticia_data = {
                "id": i,
                "titulo": artigo.titulo_extraido or "Sem título",
                "jornal": normalizar_jornal(artigo.jornal) or "N/A",
                "fato_gerador": _fato_gerador_artigo(artigo),
            }
            novas_noticias.append(noticia_data)

        clusters_existentes_data = []
        for i, cluster in enumerate(clusters_existentes):
            artigos_cluster = get_artigos_by_cluster(db, cluster.id)
            titulos = [
                a.titulo_extraido or (a.texto_processado[:80] + "...") if (a.texto_processado or "") else "Sem título"
                for a in artigos_cluster
            ]
            titulos = titulos[:10]
            jornais_no_cluster = list({normalizar_jornal(a.jornal) for a in artigos_cluster if normalizar_jornal(a.jornal)})
            # Referente do cluster por qualidade: fato_gerador com length >= 20; senão o de maior length (evita gênese fraco)
            MIN_LEN_REFERENTE = 20
            artigos_ordenados = sorted(artigos_cluster, key=lambda a: (a.created_at is None, a.created_at or datetime.min))
            referente_artigo = None
            for a in artigos_ordenados:
                fg = _fato_gerador_artigo(a)
                if len(fg) >= MIN_LEN_REFERENTE:
                    referente_artigo = a
                    break
            if not referente_artigo and artigos_ordenados:
                referente_artigo = max(artigos_ordenados, key=lambda a: len(_fato_gerador_artigo(a)))
            fato_gerador_referente = _fato_gerador_artigo(referente_artigo) if referente_artigo else (cluster.titulo_cluster or "Sem tema")
            cluster_data = {
                "cluster_id": cluster.id,
                "tema_principal": cluster.titulo_cluster,
                "fato_gerador_referente": fato_gerador_referente,
                "titulos_internos": titulos,
                "jornais_no_cluster": jornais_no_cluster,
            }
            clusters_existentes_data.append(cluster_data)
        
        # Mapeamento de ID para artigo original
        mapa_id_para_artigo = {i: artigo for i, artigo in enumerate(artigos_lote)}
        
        # ---------------------------------------------------------------
        # v2: Dicas de similaridade DESABILITADAS na ETAPA 2 (agrupamento incremental)
        # -------------------------------------------------------------------
        # MOTIVO: Embeddings de dominio (economia/governo/mercado) produzem falsos
        # positivos com threshold < 0.92, levando o LLM a agrupar artigos com
        # entidades em comum mas FATOS GERADORES diferentes (ex: "BRB+Master" com
        # "Angra 3" porque ambos sao governo/economia).
        # O agrupamento deve ser puramente baseado no julgamento do LLM sobre o
        # FATO GERADOR, que era o comportamento correto da v1.
        # As dicas v2 continuam ativas na ETAPA 4 (consolidacao) com threshold alto.
        # -------------------------------------------------------------------
        dicas_similaridade = ""
        
        # Monta o prompt incremental
        from backend.prompts import PROMPT_AGRUPAMENTO_INCREMENTAL_V2
        prompt_completo = PROMPT_AGRUPAMENTO_INCREMENTAL_V2.format(
            NOVAS_NOTICIAS=json.dumps(novas_noticias, indent=2, ensure_ascii=False),
            CLUSTERS_EXISTENTES=json.dumps(clusters_existentes_data, indent=2, ensure_ascii=False),
            FONTES_FLASHES_LIST=", ".join(FONTES_FLASHES),
        )
        # Injeta dicas de similaridade v2 (sem alterar o template do prompt)
        if dicas_similaridade:
            prompt_completo += dicas_similaridade
        
        print(f"📤 Enviando lote {numero_lote}: {len(novas_noticias)} notícias para análise...")
        
        # Chama a API para análise incremental
        try:
            response = client.generate_content(
                prompt_completo,
                generation_config={
                    'temperature': 0.1,  # Mais determinístico
                    'top_p': 0.8,
                    'max_output_tokens': 32768,  # Aumentado para suportar resposta completa do incremental
                    'candidate_count': 1
                }
            )
            
            if not response.text:
                print("❌ ERRO: API retornou resposta vazia para agrupamento incremental")
                return False
            # Resposta detalhada desativada por padrão
            
            # Extrai JSON da resposta (com fallback robusto)
            classificacoes = extrair_classificacoes_incremental_seguro(response.text)
            
            if not classificacoes or not isinstance(classificacoes, list):
                print("❌ ERRO: Resposta de agrupamento incremental inválida")
                print(f"📋 Resposta recebida: {response.text[:500]}...")
                return False
            print(f"✅ Lote {numero_lote}: {len(classificacoes)} classificações")
            
            # Processa cada classificação
            anexacoes = 0
            novos_clusters = 0

            def _normalizar_classificacao(obj: Dict[str, Any]) -> Dict[str, Any]:
                tipo_raw = (obj.get("tipo") or "").strip().lower()
                tipo_map = {
                    "attach": "anexar",
                    "append": "anexar",
                    "merge": "anexar",
                    "link": "anexar",
                    "anexar": "anexar",
                    "novo": "novo_cluster",
                    "novo cluster": "novo_cluster",
                    "novo_cluster": "novo_cluster",
                    "new": "novo_cluster",
                    "new_cluster": "novo_cluster",
                    "create": "novo_cluster",
                }
                tipo = tipo_map.get(tipo_raw, tipo_raw)
                n_id = obj.get("noticia_id")
                try:
                    if isinstance(n_id, str) and n_id.isdigit():
                        n_id = int(n_id)
                except Exception:
                    pass
                c_id = obj.get("cluster_id_existente")
                if c_id is None:
                    c_id = obj.get("existing_cluster_id") or obj.get("cluster_id")
                try:
                    if isinstance(c_id, str) and c_id.isdigit():
                        c_id = int(c_id)
                except Exception:
                    pass
                tema = obj.get("tema_principal")
                return {"tipo": tipo, "noticia_id": n_id, "cluster_id_existente": c_id, "tema_principal": tema}

            # CORREÇÃO: Cria mapa de cluster_ids válidos para validação
            cluster_ids_validos = {c.id for c in clusters_existentes}
            print(f"  📎 Lote {numero_lote}: {len(cluster_ids_validos)} clusters válidos para anexação")
            
            # CORREÇÃO: Adiciona fallback para IDs inválidos baseado no array de clusters
            def _validar_cluster_id(cluster_id_bruto: int) -> tuple:
                """Retorna (cluster_id_valido, cluster_encontrado) ou (None, None) se inválido"""
                if cluster_id_bruto in cluster_ids_validos:
                    cluster = next((c for c in clusters_existentes if c.id == cluster_id_bruto), None)
                    return (cluster_id_bruto, cluster)
                
                # FALLBACK: Se o ID parece ser um índice de array (0, 1, 2, ...), tenta mapear para o cluster real
                if 0 <= cluster_id_bruto < len(clusters_existentes):
                    cluster_real = clusters_existentes[cluster_id_bruto]
                    print(f"  🔧 FALLBACK: Mapeando índice {cluster_id_bruto} → cluster ID {cluster_real.id}")
                    return (cluster_real.id, cluster_real)
                
                return (None, None)

            tipos_encontrados: Dict[str, int] = {}
            skip_tipo_fonte = 0
            cluster_nao_encontrado = 0
            for classificacao in classificacoes:
                try:
                    cls = _normalizar_classificacao(classificacao)
                    tipo = cls.get("tipo")
                    noticia_id = cls.get("noticia_id")
                    tipos_encontrados[tipo or "<vazio>"] = tipos_encontrados.get(tipo or "<vazio>", 0) + 1
                    
                    if noticia_id not in mapa_id_para_artigo:
                        if debug:
                            print(f"  ⚠️ ID de notícia inválido: {noticia_id}")
                        continue
                    
                    artigo = mapa_id_para_artigo[noticia_id]
                    
                    if tipo == "anexar":
                        # Anexa a cluster existente com validação melhorada
                        cluster_id_bruto = cls.get("cluster_id_existente")
                        if cluster_id_bruto is not None:
                            cluster_id_valido, cluster_existente = _validar_cluster_id(cluster_id_bruto)
                            
                            if cluster_existente:
                                artigo_tf = getattr(artigo, 'tipo_fonte', 'brasil_online') or 'brasil_online'
                                cluster_tf = getattr(cluster_existente, 'tipo_fonte', 'brasil_online') or 'brasil_online'
                                # Converte 'nacional' legado do cluster para equivalente físico/online do artigo
                                if cluster_tf == 'nacional':
                                    cluster_tf = artigo_tf
                                if artigo_tf != cluster_tf:
                                    skip_tipo_fonte += 1
                                    # Fallback: trata como novo cluster (o if abaixo captura)
                                    tipo = "novo_cluster"
                                else:
                                    associate_artigo_to_cluster(db, artigo.id, cluster_existente.id)
                                    anexacoes += 1
                                    continue
                            else:
                                cluster_nao_encontrado += 1
                                tipo = "novo_cluster"
                        else:
                            cluster_nao_encontrado += 1
                            tipo = "novo_cluster"
                    
                    # CORRECAO: if (nao elif) para capturar fallbacks de "anexar" que mudaram tipo
                    if tipo == "novo_cluster":
                        # Cria novo cluster; se título genérico, gera fallback curto para evitar "sem título"
                        tema_raw = cls.get("tema_principal") or ""
                        tema_principal = tema_raw
                        if titulo_e_generico(tema_principal):
                            tema_principal = gerar_titulo_fallback_curto(artigo.texto_processado or artigo.texto_bruto or "")
                            if titulo_e_generico(tema_principal):
                                tema_principal = f"Evento {artigo.id}"

                        # Calcula embedding do artigo
                        embedding_medio = None
                        if artigo.embedding:
                            embedding_medio = artigo.embedding
                        
                        # Detecta tipo de fonte do artigo
                        # Se o artigo não tiver tipo_fonte, infere por 'jornal' ou 'fonte_original'
                        tipo_fonte = getattr(artigo, 'tipo_fonte', None)
                        if not tipo_fonte:
                            try:
                                from backend.utils import inferir_tipo_fonte_por_jornal as _infer_tf
                            except Exception:
                                from utils import inferir_tipo_fonte_por_jornal as _infer_tf
                            jornal = (getattr(artigo, 'jornal', None) or '')
                            tipo_fonte = _infer_tf(jornal)
                        
                        # Define tipo_fonte do novo cluster seguindo a regra de precedência
                        # 1) internacional se artigo internacional
                        # 2) brasil_fisico se artigo físico
                        # 3) brasil_online caso contrário
                        if tipo_fonte == 'internacional':
                            tipo_fonte_cluster = 'internacional'
                        elif tipo_fonte == 'brasil_fisico':
                            tipo_fonte_cluster = 'brasil_fisico'
                        else:
                            tipo_fonte_cluster = 'brasil_online'

                        # Cria cluster
                        from backend.models import ClusterEventoCreate
                        cluster_data = ClusterEventoCreate(
                            titulo_cluster=tema_principal,
                            resumo_cluster=None,  # Será preenchido na ETAPA 3
                            tag="PENDING",  # Será definido na ETAPA 3
                            prioridade="PENDING",  # Será definido na ETAPA 3
                            embedding_medio=embedding_medio,
                            tipo_fonte=tipo_fonte_cluster
                        )

                        cluster = create_cluster(db, cluster_data)
                        associate_artigo_to_cluster(db, artigo.id, cluster.id)
                        novos_clusters += 1
                        tprev = (artigo.titulo_extraido or artigo.texto_processado or "").replace("\n"," ")[:100]
                        # Só mostra novos clusters internacionais ou em debug
                        if debug and tipo_fonte == 'internacional':
                            print(f"  🌍 novo-cluster: '{tema_principal[:80]}' com '{tprev[:50]}...'")
                    
                    else:
                        print(f"  ⚠️ Tipo de classificação inválido: {tipo}")
                
                except Exception as e:
                    print(f"  ❌ Erro ao processar classificação: {e}")
                    continue
            if skip_tipo_fonte or cluster_nao_encontrado:
                print(f"  ↪ Resumo lote: {anexacoes} anexações, {novos_clusters} novos clusters | skip tipo_fonte: {skip_tipo_fonte} | cluster não encontrado: {cluster_nao_encontrado}")
            if debug and (anexacoes + novos_clusters) == 0 and isinstance(classificacoes, list) and len(classificacoes) > 0:
                print(f"  ⚠️ Diagnóstico: {len(classificacoes)} itens, nenhum anexado/criado. Tipos: {tipos_encontrados}")
            return (anexacoes, novos_clusters)
            
        except Exception as e:
            print(f"❌ ERRO na chamada da API incremental: {e}")
            return False
        
    except Exception as e:
        print(f"❌ ERRO: Falha no processamento do lote {numero_lote}: {e}")
        import traceback
        traceback.print_exc()
        return False


def agrupar_noticias_com_prompt(db: Session, client, day_str: Optional[str] = None) -> bool:
    """
    Agrupa notícias usando prompt, agora processando em lotes (batches)
    para evitar truncamento de resposta da API com grandes volumes.
    """
    try:
        # Busca notícias prontas para agrupamento, filtrando por data se especificada
        query = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.is_(None)
        )
        
        # Se uma data específica for fornecida, filtra por ela
        if day_str:
            query = query.filter(func.date(ArtigoBruto.created_at) == day_str)
        
        artigos_para_agrupar = query.all()
        
        if not artigos_para_agrupar:
            print("INFO: Nenhum artigo novo para agrupamento.")
            return True
        
        print(f"🔗 INICIANDO AGRUPAMENTO: {len(artigos_para_agrupar)} em lotes de {BATCH_SIZE_AGRUPAMENTO}.")

        # Isolamento estrito por tipo_fonte: três grupos (brasil_fisico, brasil_online, internacional)
        def _tipo_fonte(a):
            t = getattr(a, 'tipo_fonte', None) or 'brasil_fisico'
            return 'brasil_fisico' if t == 'nacional' else t
        artigos_brasil_fisico = [a for a in artigos_para_agrupar if _tipo_fonte(a) == 'brasil_fisico']
        artigos_brasil_online = [a for a in artigos_para_agrupar if _tipo_fonte(a) == 'brasil_online']
        artigos_internacional = [a for a in artigos_para_agrupar if _tipo_fonte(a) == 'internacional']
        print(f"   📊 Artigos: {len(artigos_brasil_fisico)} brasil_fisico, {len(artigos_brasil_online)} brasil_online, {len(artigos_internacional)} internacional.")
        
        artigos_sem_tipo = [a for a in artigos_para_agrupar if not hasattr(a, 'tipo_fonte') or a.tipo_fonte is None]
        if artigos_sem_tipo:
            print(f"⚠️ AVISO: {len(artigos_sem_tipo)} artigos sem tipo_fonte definido (tratados como brasil_fisico)")
        
        def _titulo_key(a):
            t = (a.titulo_extraido or '').strip().lower()
            return t
        artigos_brasil_fisico.sort(key=_titulo_key)
        artigos_brasil_online.sort(key=_titulo_key)
        artigos_internacional.sort(key=_titulo_key)

        def _processar_lotes(rotulo: str, artigos_lista: list) -> tuple:
            if not artigos_lista:
                return (0, 0)
            print(f"🔗 AGRUPAMENTO ({rotulo}): {len(artigos_lista)} artigos em lotes de {BATCH_SIZE_AGRUPAMENTO}.")
            # Mapeamento de ID para artigo original para o conjunto deste rotulo
            mapa_id_para_artigo_local = {i: artigo for i, artigo in enumerate(artigos_lista)}
            lotes_local = [artigos_lista[i:i + BATCH_SIZE_AGRUPAMENTO] for i in range(0, len(artigos_lista), BATCH_SIZE_AGRUPAMENTO)]
            clusters_criados_local = 0
            artigos_agrupados_local = 0

            for num_lote, lote_artigos in enumerate(lotes_local, 1):
                # Isolamento estrito: lote não pode misturar tipo_fonte
                tipos_lote = {_tipo_fonte(a) for a in lote_artigos}
                if len(tipos_lote) > 1:
                    raise ValueError(
                        f"Lote {rotulo} {num_lote} mistura tipo_fonte: {tipos_lote}. "
                        "Cada lote deve ter um único tipo_fonte (brasil_fisico, brasil_online ou internacional)."
                    )
                print(f"\n--- Lote {rotulo} {num_lote}/{len(lotes_local)} ({len(lote_artigos)} artigos) ---")
                # Prepara dados apenas para o lote atual
                noticias_lote_para_prompt = []
                mapa_id_lote_para_artigo = {}
                def _entidade_acao(a):
                    m = (a.metadados or {}) or {}
                    fg = m.get("fato_gerador")
                    if isinstance(fg, dict):
                        ent = (fg.get("entidade_alvo") or "").strip()
                        acao = (fg.get("acao_material") or "").strip()
                        if ent and acao:
                            return (ent[:80], acao[:120])
                        padrao = (fg.get("fato_gerador_padronizado") or "").strip()
                        if padrao and " - " in padrao:
                            parts = padrao.split(" - ", 1)
                            return (parts[0].strip()[:80], parts[1].strip()[:120])
                        if padrao:
                            return (padrao[:80], "")
                    titulo = (a.titulo_extraido or "Sem título")[:80]
                    return (titulo, "")
                # Excluir artigos sem fato gerador válido (evitar clusters "N/A - N/A"); marcar como erro para não reentrar
                lote_valido = []
                for art in lote_artigos:
                    ent_alvo, acao_mat = _entidade_acao(art)
                    titulo_item = (art.titulo_extraido or gerar_titulo_fallback_curto(art.texto_processado or art.texto_bruto or "") or "Sem título")[:120]
                    ent_final = ent_alvo or "N/A"
                    acao_final = acao_mat or titulo_item or "N/A"
                    if ent_final == "N/A" or acao_final == "N/A" or (not (ent_alvo and ent_alvo.strip()) and not (acao_mat or titulo_item)):
                        metadados_art = dict(art.metadados or {})
                        metadados_art["fato_gerador_erro"] = True
                        art.metadados = metadados_art
                        update_artigo_status(db, art.id, "erro")
                        db.commit()
                        if num_lote == 1:
                            print(f"  ⚠️ Artigo ID {art.id} excluído do lote (sem fato gerador válido); marcado como erro.")
                        continue
                    lote_valido.append(art)
                if not lote_valido:
                    print(f"  ⚠️ Lote {rotulo} {num_lote}: todos os artigos sem fato gerador válido; pulando.")
                    continue
                lote_artigos = lote_valido
                for i, artigo in enumerate(lote_artigos):
                    ent_alvo, acao_mat = _entidade_acao(artigo)
                    titulo_item = (artigo.titulo_extraido or gerar_titulo_fallback_curto(artigo.texto_processado or artigo.texto_bruto or "")) or "Sem título"
                    noticia_data = {
                        "id": i,
                        "entidade_alvo": ent_alvo or "N/A",
                        "acao_material": acao_mat or titulo_item[:120],
                        "jornal": normalizar_jornal(artigo.jornal) or "N/A",
                    }
                    noticias_lote_para_prompt.append(noticia_data)
                    mapa_id_lote_para_artigo[i] = artigo  # Mapeia o ID do lote para o objeto artigo completo

                # v2: Dicas de similaridade DESABILITADAS na ETAPA 2 (agrupamento por lote)
                # Mesmo motivo: embeddings de dominio geram falsos positivos que levam
                # o LLM a misturar fatos geradores diferentes no mesmo cluster.
                dicas_lote = ""

                # Monta o prompt completo para o lote
                prompt_completo = f"""
{PROMPT_AGRUPAMENTO_V1}

NOTÍCIAS PARA AGRUPAR (LOTE {rotulo} {num_lote}/{len(lotes_local)}):
{json.dumps(noticias_lote_para_prompt, indent=2, ensure_ascii=False)}

IMPORTANTE: Retorne APENAS o JSON válido para este lote.
{dicas_lote}
"""

                print(f"📤 ENVIANDO Lote {rotulo} {num_lote} para a API...")
                try:
                    # Chama a API para o lote
                    response = client.generate_content(
                        prompt_completo,
                        generation_config={
                            'temperature': 0.05,  # determinístico
                            'top_p': 0.7,
                            'max_output_tokens': MAX_OUTPUT_TOKENS_STAGE2,
                            'candidate_count': 1,
                            'top_k': 10
                        }
                    )

                    if not response.text:
                        print(f"⚠️ AVISO: API retornou resposta vazia para o lote {rotulo} {num_lote}. Pulando este lote.")
                        continue

                    print(f"📥 RESPOSTA RECEBIDA para o Lote {rotulo} {num_lote}: {len(response.text)} caracteres")

                    # Usa a função de extração robusta
                    grupos_brutos = extrair_grupos_agrupamento_seguro(response.text)

                    if not grupos_brutos or not isinstance(grupos_brutos, list):
                        print(f"❌ ERRO: Resposta de agrupamento inválida para o lote {rotulo} {num_lote}.")
                        continue

                    print(f"✅ SUCESSO LOTE {rotulo} {num_lote}: {len(grupos_brutos)} grupos criados.")

                    # Processa os clusters do lote
                    for grupo_data in grupos_brutos:
                        try:
                            tema_principal = grupo_data.get("tema_principal", f"Grupo Lote {rotulo} {num_lote}")
                            ids_no_lote = grupo_data.get("ids_originais", [])
                            artigos_do_grupo = [mapa_id_lote_para_artigo[id_lote] for id_lote in ids_no_lote if id_lote in mapa_id_lote_para_artigo]

                            if not artigos_do_grupo:
                                continue

                            # ETAPA 2: SÓ AGRUPA - valores PENDING, serão definidos na ETAPA 3
                            prioridade_grupo = "PENDING"  # Será definido na ETAPA 3
                            tag_grupo = "PENDING"  # Será definido na ETAPA 3

                            # Calcula embedding médio do grupo; tipo_fonte segue o rótulo do lote
                            embeddings = []
                            for artigo in artigos_do_grupo:
                                if artigo.embedding:
                                    embeddings.append(bytes_to_embedding(artigo.embedding))
                            
                            # Regra de tipo_fonte do cluster (força idioma/precedência):
                            # 1) Se QUALQUER artigo for internacional → cluster internacional
                            # 2) Senão, se houver QUALQUER artigo 'brasil_fisico' → cluster brasil_fisico
                            # 3) Caso contrário → brasil_online
                            tipos_artigos = [getattr(a, 'tipo_fonte', 'brasil_online') or 'brasil_online' for a in artigos_do_grupo]
                            if any(t == 'internacional' for t in tipos_artigos):
                                tipo_fonte = 'internacional'
                            elif any(t == 'brasil_fisico' for t in tipos_artigos):
                                tipo_fonte = 'brasil_fisico'
                            else:
                                tipo_fonte = 'brasil_online'

                            embedding_medio = None
                            if embeddings:
                                import numpy as np
                                embedding_medio = np.mean(embeddings, axis=0).tobytes()

                            # Cria cluster
                            from backend.models import ClusterEventoCreate
                            cluster_data = ClusterEventoCreate(
                                titulo_cluster=tema_principal,
                                resumo_cluster=None,  # Será preenchido na ETAPA 3
                                tag=tag_grupo,
                                prioridade=prioridade_grupo,
                                embedding_medio=embedding_medio,
                                tipo_fonte=tipo_fonte
                            )

                            cluster = create_cluster(db, cluster_data)
                            clusters_criados_local += 1

                            # Associa artigos ao cluster
                            for artigo in artigos_do_grupo:
                                associate_artigo_to_cluster(db, artigo.id, cluster.id)
                                artigos_agrupados_local += 1


                        except Exception as e:
                            print(f"  ❌ Erro ao criar cluster no lote {rotulo} {num_lote}: {e}")
                            continue

                except Exception as e_lote:
                    print(f"❌ ERRO CRÍTICO ao processar o lote {rotulo} {num_lote}: {e_lote}")
                    continue  # Pula para o próximo lote

            return (clusters_criados_local, artigos_agrupados_local)

        clusters_criados_total = 0
        artigos_agrupados_total = 0
        c_f, a_f = _processar_lotes('BRASIL_FISICO', artigos_brasil_fisico)
        clusters_criados_total += c_f
        artigos_agrupados_total += a_f
        c_o, a_o = _processar_lotes('BRASIL_ONLINE', artigos_brasil_online)
        clusters_criados_total += c_o
        artigos_agrupados_total += a_o
        c_int, a_int = _processar_lotes('INTERNACIONAL', artigos_internacional)
        clusters_criados_total += c_int
        artigos_agrupados_total += a_int

        print(f"\n🎉 ETAPA 2 CONCLUÍDA: {clusters_criados_total} clusters criados, {artigos_agrupados_total} artigos agrupados no total.")

        # Marca artigos como "processado" após clusterização
        artigos_agrupados = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.isnot(None)  # Artigos que foram agrupados
        ).all()
        marcar_artigos_processados(db, artigos_agrupados)

        # Fallback de agrupamento removido para simplificação e evitar misturas inesperadas

        return True
        
    except Exception as e:
        print(f"❌ ERRO GERAL na função de agrupamento: {e}")
        import traceback
        traceback.print_exc()
        return False

def processar_artigos_em_lote(limite: int = 10) -> bool:
    """
    Processa artigos em lote (modo alternativo para reprocessamento).
    Usado quando queremos reagrupar todos os artigos do dia.
    """
    db = SessionLocal()
    try:
        # Busca artigos pendentes
        artigos_pendentes = get_artigos_pendentes(db, limite=limite)
        
        if not artigos_pendentes:
            print("✅ Nenhum artigo pendente encontrado")
            return True
        
        print(f"📰 Encontrados {len(artigos_pendentes)} artigos pendentes")
        
        # ETAPA 1: Processa todos os artigos pendentes
        print(f"\n🔄 ETAPA 1: Processando {len(artigos_pendentes)} artigos pendentes...")
        
        sucessos = 0
        erros = 0
        
        for i, artigo in enumerate(artigos_pendentes, 1):
            print(f"  📤 Processando artigo {i}/{len(artigos_pendentes)} (ID: {artigo.id})...")
            
            # Processa artigo sem clusterização automática
            if processar_artigo_sem_cluster(db, artigo.id, client):
                sucessos += 1
            else:
                erros += 1
            
            time.sleep(0.1)
        
        print(f"\n✅ Processamento de artigos finalizado:")
        print(f"   📰 Artigos processados: {len(artigos_pendentes)}")
        print(f"   ✅ Sucessos: {sucessos}")
        print(f"   ❌ Erros: {erros}")
        
        # ETAPA 2: Busca artigos processados hoje para agrupamento
        hoje = get_date_brasil_str()
        artigos_hoje = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "processado",
            ArtigoBruto.processed_at >= hoje
        ).all()
        
        if not artigos_hoje:
            print("✅ Nenhum artigo processado hoje para agrupamento")
            return True
        
        print(f"\n🔗 ETAPA 2: Agrupando {len(artigos_hoje)} artigos processados hoje...")
        
        # ETAPA 3: Agrupa notícias por similaridade
        grupos = agrupar_noticias_por_similaridade(db, artigos_hoje)
        
        if not grupos:
            print("✅ Nenhum grupo formado")
            return True
        
        # ETAPA 4: Gera resumos apenas para grupos P1 e P2
        print(f"\n📝 ETAPA 3: Gerando resumos para {len(grupos)} grupos...")
        
        clusters_criados = 0
        resumos_gerados = 0
        
        for i, grupo in enumerate(grupos, 1):
            print(f"  📝 Processando grupo {i}/{len(grupos)} com {len(grupo)} notícias...")
            
            # Verifica prioridade do grupo
            prioridade_grupo = grupo[0].prioridade
            print(f"    📊 Prioridade do grupo: {prioridade_grupo}")
            
            # Cria cluster
            try:
                from backend.models import ClusterEventoCreate
                
                # Calcula embedding médio do cluster
                embeddings = []
                for artigo in grupo:
                    if artigo.embedding:
                        embeddings.append(bytes_to_embedding(artigo.embedding))
                
                embedding_medio = None
                if embeddings:
                    import numpy as np
                    embedding_medio = np.mean(embeddings, axis=0).tobytes()
                
                # Detecta tipo_fonte do grupo
                tipos_artigos = [getattr(a, 'tipo_fonte', 'brasil_online') or 'brasil_online' for a in grupo]
                if any(t == 'internacional' for t in tipos_artigos):
                    tipo_fonte_grupo = 'internacional'
                elif any(t == 'brasil_fisico' for t in tipos_artigos):
                    tipo_fonte_grupo = 'brasil_fisico'
                else:
                    tipo_fonte_grupo = 'brasil_online'
                
                # Cria cluster com dados básicos
                cluster_data = ClusterEventoCreate(
                    titulo_cluster=f"Cluster {i} - {len(grupo)} notícias",
                    resumo_cluster=None,  # Será preenchido se necessário
                    tag=grupo[0].tag,
                    prioridade=prioridade_grupo,
                    embedding_medio=embedding_medio,
                    tipo_fonte=tipo_fonte_grupo
                )
                
                # Cria o cluster
                cluster = create_cluster(db, cluster_data)
                clusters_criados += 1
                
                # Associa artigos ao cluster
                for artigo in grupo:
                    associate_artigo_to_cluster(db, artigo.id, cluster.id)
                
                # Gera resumo apenas para P1 e P2
                if prioridade_grupo in ['P1_CRITICO', 'P2_ESTRATEGICO']:
                    print(f"    📝 Gerando resumo para cluster {cluster.id} (Prioridade: {prioridade_grupo})...")
                    
                if gerar_resumo_cluster(db, cluster.id, client):
                    resumos_gerados += 1
                    print(f"    ✅ Resumo gerado com sucesso")
                else:
                    print(f"    ❌ Falha ao gerar resumo")
                # else:
                #     print(f"    ℹ️ Cluster {cluster.id} (Prioridade: {prioridade_grupo}) não requer resumo. Pulando.")
                
            except Exception as e:
                print(f"    ❌ Erro ao criar cluster: {e}")
                continue
        
        print(f"\n🎉 Processamento em lote finalizado:")
        print(f"   📰 Artigos processados: {sucessos}")
        print(f"   🔗 Clusters criados: {clusters_criados}")
        print(f"   📝 Resumos gerados: {resumos_gerados}")
        print(f"   📊 Grupos processados: {len(grupos)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro geral no processamento: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

# ==============================================================================
# ENRIQUECIMENTO GRAPH-RAG v2.0 (integrado ao pipeline principal)
# ==============================================================================

def enriquecer_artigo_v2(db: Session, id_artigo: int, noticia_data: dict, client) -> dict:
    """
    Enriquecimento Graph-RAG v2 para um artigo individual.
    Chamado dentro da ETAPA 1 (processar_artigo_sem_cluster) para cada artigo.
    
    Executa 3 sub-etapas:
      A) Gera embedding_v2 (768d Gemini) e salva no artigo
      B) Extrai entidades via LLM (Gemini Flash)
      C) Resolve entidades e persiste no grafo de conhecimento
    
    Degradacao graciosa: se qualquer sub-etapa falhar, as seguintes continuam.
    
    Returns:
        Dict com stats: {embedding_ok, entities_count, edges_count}
    """
    stats = {"embedding_ok": False, "entities_count": 0, "edges_count": 0}
    
    titulo = noticia_data.get('titulo', '')
    texto = noticia_data.get('texto_completo', '')
    
    # ---------------------------------------------------------------
    # SUB-ETAPA A: Gerar embedding_v2 (Gemini 768d) - ~100ms
    # ---------------------------------------------------------------
    embedding_bytes = None
    try:
        texto_emb = f"{titulo} {texto}"
        embedding_bytes = gerar_embedding_v2(texto_emb)
        if embedding_bytes:
            artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
            if artigo and not artigo.embedding_v2:
                artigo.embedding_v2 = embedding_bytes
                db.commit()
                stats["embedding_ok"] = True
    except Exception as e:
        print(f"  [v2-emb] Artigo {id_artigo}: {str(e)[:80]}")
        try:
            db.rollback()
        except Exception:
            pass
    
    # ---------------------------------------------------------------
    # SUB-ETAPA B: Extrair entidades via LLM (Gemini Flash) - ~1-2s
    # ---------------------------------------------------------------
    valid_entities = []
    try:
        texto_ner = f"Titulo: {titulo}\n\n{texto[:4000]}"
        prompt = PROMPT_ENTITY_EXTRACTION.format(texto=texto_ner)
        
        response = client.generate_content(
            prompt,
            generation_config={'temperature': 0.2, 'max_output_tokens': 2048}
        )
        
        from backend.utils import extrair_json_da_resposta as _extrair_json
        resultado = _extrair_json(response.text)
        
        if resultado and isinstance(resultado, dict):
            entities_raw = resultado.get("entities", [])
            for e in entities_raw:
                if isinstance(e, dict) and e.get("name") and len(e["name"].strip()) >= 2:
                    valid_entities.append({
                        "name": e["name"].strip(),
                        "type": e.get("type", "ORG").upper(),
                        "role": e.get("role", "MENTIONED").upper(),
                        "sentiment": float(e.get("sentiment", 0.0)),
                        "context": str(e.get("context", ""))[:200],
                    })
            stats["entities_count"] = len(valid_entities)
    except Exception as e:
        print(f"  [v2-ner] Artigo {id_artigo}: {str(e)[:80]}")
    
    # ---------------------------------------------------------------
    # SUB-ETAPA C: Resolver entidades e persistir no grafo - ~50ms
    # ---------------------------------------------------------------
    if valid_entities:
        try:
            edges = link_artigo_to_entities(db, id_artigo, valid_entities)
            stats["edges_count"] = len(edges)
        except Exception as e:
            print(f"  [v2-graph] Artigo {id_artigo}: {str(e)[:80]}")
            try:
                db.rollback()
            except Exception:
                pass
    
    return stats


def processar_artigo_sem_cluster(db: Session, id_artigo: int, client) -> bool:
    """
    Processa um artigo sem fazer clusterização automática.
    Usado no modo em lote.
    """
    try:
        # Busca dados brutos do artigo
        artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == id_artigo).first()
        if not artigo:
            return False
        
        # Processa o artigo sem clusterização (copia a lógica do processar_artigo_pipeline mas sem a ETAPA 7)
        create_log(db, "INFO", "processor", 
                  f"Iniciando processamento do artigo {id_artigo} (sem clusterização)",
                  {"fonte": artigo.fonte_coleta})
        
        # ETAPA 1: Verificar se já tem metadados estruturados
        metadados = artigo.metadados or {}
        
        # Se já tem dados estruturados (JSON), usa diretamente
        if metadados.get('titulo') and metadados.get('fonte_original'):
            # sucesso silencioso: sem prints verbose
            
            # Migra tag antiga se necessário
            tag_original = metadados.get('tag', 'Economia e Tecnologia')
            tag_migrada = migrar_tag_antiga_para_nova(tag_original)
            
            noticia_data = {
                'titulo': metadados.get('titulo', 'Sem título'),
                'texto_completo': artigo.texto_bruto,
                'jornal': metadados.get('fonte_original', 'Fonte desconhecida'),
                'autor': 'N/A',  # Não temos autor nos dados originais
                'pagina': '1',
                'data': metadados.get('data_publicacao') or get_date_brasil_str(),
                'categoria': metadados.get('categoria', 'Geral'),
                'tag': 'PENDING',  # Será redefinida na ETAPA 3
                'prioridade': 'PENDING'  # Será redefinida na ETAPA 3
            }
            
        else:
            # Para PDFs ou artigos sem estrutura, faz extração básica (silencioso em sucesso)

            # Extração básica sem LLM
            linhas = artigo.texto_bruto.split('\n')
            titulo = linhas[0].strip() if linhas else "Sem título"

            # Pré-filtro de lixo publicitário (curto-circuito) — desativado temporariamente
            # if eh_lixo_publicitario(titulo, artigo.texto_bruto):
            #     prev = (titulo or "").replace("\n"," ")[:120]
            #     print(f"    EXCLUIDO: LIXO_PUBLICITARIO (pré-migração) - '{prev}'")
            #     update_artigo_status(db, id_artigo, 'irrelevante')
            #     return True

            # Tenta identificar jornal/fonte dos metadados
            jornal = metadados.get('fonte_original') or 'Fonte desconhecida'

            noticia_data = {
                'titulo': titulo,
                'texto_completo': artigo.texto_bruto,
                'jornal': jornal,
                'autor': 'N/A',
                'pagina': '1',
                'data': metadados.get('data_publicacao') or get_date_brasil_str(),
                'categoria': metadados.get('categoria', 'Geral'),
                'tag': 'PENDING',  # Será redefinida na ETAPA 3
                'prioridade': 'PENDING'  # Será redefinida na ETAPA 3
            }
        
        # ETAPA 2: Migração e correção de dados
        from backend.processing import migrar_noticia_cache_legado, corrigir_tag_invalida
        noticia_data = migrar_noticia_cache_legado(noticia_data)
        
        # CORREÇÃO: Preserva o tipo_fonte original do artigo durante a migração
        if hasattr(artigo, 'tipo_fonte') and artigo.tipo_fonte:
            noticia_data['tipo_fonte'] = artigo.tipo_fonte
            if artigo.tipo_fonte == 'internacional':
                print(f"    🔍 DEBUG: Artigo {id_artigo} preserva tipo_fonte='internacional' durante migração")
        
        # Corrige a tag se necessário
        if 'tag' in noticia_data:
            noticia_data['tag'] = corrigir_tag_invalida(noticia_data['tag'])
        
        # Pré-filtro de lixo publicitário com dados migrados também (dupla checagem) — desativado temporariamente
        # if eh_lixo_publicitario(noticia_data.get('titulo'), noticia_data.get('texto_completo')):
        #     prev = (noticia_data.get('titulo') or "").replace("\n"," ")[:120]
        #     print(f"    EXCLUIDO: LIXO_PUBLICITARIO (pós-migração) - '{prev}'")
        #     update_artigo_status(db, id_artigo, 'irrelevante')
        #     return True

        # Garante título curto e útil antes da validação (evita 'Sem título')
        if not noticia_data.get('titulo') or titulo_e_generico(noticia_data.get('titulo')):
            noticia_data['titulo'] = gerar_titulo_fallback_curto(noticia_data.get('texto_completo'))

        # ETAPA 3: Validação com Pydantic
        try:
            noticia_obj = Noticia(**noticia_data)
            noticia_validada = noticia_obj.model_dump()
            # sucesso silencioso em validação
        except Exception as e:
            print(f"❌ Artigo {id_artigo}: validação Pydantic falhou - {str(e)[:100]}...")
            create_log(db, "ERROR", "processor",
                      f"Erro de validação Pydantic do artigo {id_artigo}: {e}")
            update_artigo_status(db, id_artigo, 'erro')
            return False

        # ETAPA 3.5: Extração de fato gerador (contrato estruturado: entidade_alvo + acao_material)
        fato_gerador_ok = False
        _fato_fail_reason = ""
        existing_fato = (metadados or {}).get("fato_gerador") if isinstance(metadados, dict) else None
        if existing_fato and isinstance(existing_fato, dict):
            if (existing_fato.get("entidade_alvo") and existing_fato.get("acao_material")) or existing_fato.get("fato_gerador_padronizado"):
                fato_gerador_ok = True
        if not fato_gerador_ok:
            from backend.prompts import PROMPT_EXTRACAO_FATO_GERADOR_V1
            from backend.models import FatoGeradorContract
            trecho = (noticia_validada.get("texto_completo") or "")[:2000]
            titulo_artigo = noticia_validada.get('titulo', '(sem titulo)')
            payload_fato = f"Título: {titulo_artigo}\n\nTrecho:\n{trecho}"
            prompt_fato = PROMPT_EXTRACAO_FATO_GERADOR_V1.strip() + "\n\n" + payload_fato
            try:
                resp_fato = client.generate_content(
                    prompt_fato,
                    generation_config={"temperature": 0.1, "max_output_tokens": 512}
                )
                text_fato = (resp_fato.text or "").strip()
                status_json, raw_json = extrair_json_da_resposta(text_fato)
                if status_json.startswith("SUCESSO") and raw_json:
                    obj = raw_json[0] if isinstance(raw_json, list) and raw_json else raw_json
                    if isinstance(obj, dict):
                        ent = (obj.get("entidade_alvo") or "").strip() or (obj.get("entidade_primaria") or "").strip()
                        acao = (obj.get("acao_material") or "").strip() or (obj.get("verbo_acao_financeira") or "").strip()
                        val = (obj.get("valor_financeiro") or obj.get("valor_envolvido") or "N/A").strip() or "N/A"
                        if ent and acao:
                            contract = FatoGeradorContract(
                                entidade_alvo=ent[:80],
                                acao_material=acao[:120],
                                valor_financeiro=val[:80] if val != "N/A" else "N/A",
                            )
                            metadados_novo = dict(artigo.metadados or {})
                            dump = contract.model_dump()
                            dump["fato_gerador_padronizado"] = dump.get("fato_gerador_padronizado") or f"{contract.entidade_alvo} - {contract.acao_material}"[:200]
                            metadados_novo["fato_gerador"] = dump
                            artigo.metadados = metadados_novo
                            db.commit()
                            fato_gerador_ok = True
                        else:
                            _fato_fail_reason = f"entidade={repr(ent)}, acao={repr(acao)} (campos vazios no JSON)"
                    else:
                        _fato_fail_reason = f"LLM retornou tipo {type(obj).__name__} em vez de dict"
                else:
                    _fato_fail_reason = f"parse JSON falhou: {status_json}"
                    if text_fato:
                        _fato_fail_reason += f" | resposta: {text_fato[:150]}"
            except Exception as e_fato:
                _fato_fail_reason = f"excecao: {e_fato}"
                create_log(db, "WARNING", "processor", f"Extração fato gerador artigo {id_artigo}: {e_fato}")
            if not fato_gerador_ok:
                metadados_novo = dict(artigo.metadados or {})
                metadados_novo["fato_gerador_erro"] = True
                metadados_novo["fato_gerador_motivo"] = _fato_fail_reason[:300]
                artigo.metadados = metadados_novo
                db.commit()
                titulo_curto = (titulo_artigo or "")[:60]
                print(f"❌ Artigo {id_artigo} ({titulo_curto}): fato gerador falhou — {_fato_fail_reason}")
                create_log(db, "ERROR", "processor", f"Fato gerador falhou {id_artigo}: {_fato_fail_reason[:200]}")
                update_artigo_status(db, id_artigo, "erro")
                return False

        # ETAPA 4: Gerar embedding
        from backend.processing import gerar_embedding
        texto_para_embedding = f"{noticia_validada['titulo']} {noticia_validada['texto_completo']}"
        embedding_artigo = gerar_embedding(texto_para_embedding)
        
        if not embedding_artigo:
            create_log(db, "WARNING", "processor", 
                      f"Falha ao gerar embedding do artigo {id_artigo}")
            import numpy as np
            embedding_artigo = np.zeros(384, dtype=np.float32).tobytes()
        
        # ETAPA 5: Atualizar artigo com dados processados (SEM clusterização)
        dados_processados = {
            'titulo': noticia_validada['titulo'],
            'texto_completo': noticia_validada['texto_completo'],  # Este será salvo em texto_processado
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
        
        # CORREÇÃO: Preserva o tipo_fonte original do artigo
        tipo_fonte_original = getattr(artigo, 'tipo_fonte', None)
        if tipo_fonte_original:
            dados_processados['tipo_fonte'] = tipo_fonte_original
            if tipo_fonte_original == 'internacional':
                print(f"🌍 Artigo {id_artigo}: tipo_fonte='internacional'")

        # IMPORTANTE: Preserva o texto_bruto original e salva o processado separadamente
        # Etapa 1 NÃO executa prompts/LLM. Mantém o texto processado igual ao original.

        # Atualiza dados processados e marca como "pronto_agrupar"
        update_artigo_dados_sem_status(db, id_artigo, dados_processados, embedding_artigo)

        # ETAPA 4.5 (v2): Enriquecimento Graph-RAG
        # Gera embedding_v2 (768d), extrai entidades via LLM, persiste no grafo.
        # Degradacao graciosa: se falhar, o artigo continua normalmente.
        v2_stats = {"embedding_ok": False, "entities_count": 0, "edges_count": 0}
        try:
            v2_stats = enriquecer_artigo_v2(db, id_artigo, noticia_data, client)
            if v2_stats.get("embedding_ok") or v2_stats.get("entities_count"):
                # Log apenas quando algo de v2 funcionou (silencioso caso contrario)
                if tipo_fonte_original == 'internacional':
                    print(f"🌍 Artigo {id_artigo}: internacional + v2 (emb={v2_stats['embedding_ok']}, ent={v2_stats['entities_count']}, edges={v2_stats['edges_count']})")
        except Exception as e:
            # v2 nunca bloqueia o pipeline principal
            print(f"  [v2] Artigo {id_artigo}: falha nao-critica - {str(e)[:80]}")

        # Marca como pronto para agrupamento (status mais curto)
        update_artigo_status(db, id_artigo, "pronto_agrupar")

        # NÃO faz clusterização aqui - será feita na ETAPA 2

        create_log(db, "INFO", "processor",
                  f"Artigo {id_artigo} pronto para agrupamento")

        # Só mostra erros ou casos especiais (se v2 nao imprimiu)
        if tipo_fonte_original == 'internacional' and not (v2_stats.get("embedding_ok") or v2_stats.get("entities_count")):
            print(f"🌍 Artigo {id_artigo}: internacional processado (v2 indisponivel)")

        return True

    except Exception as e:
        print(f"❌ Artigo {id_artigo}: erro geral - {str(e)[:100]}...")
        create_log(db, "ERROR", "processor",
                  f"Erro geral no processamento do artigo {id_artigo}: {e}")
        update_artigo_status(db, id_artigo, 'erro')
        return False

def agrupar_noticias_por_similaridade(db: Session, artigos_processados: List[ArtigoBruto]) -> List[List[ArtigoBruto]]:
    """
    Agrupa notícias por similaridade usando embeddings.
    Usado no modo em lote.
    """
    if not artigos_processados:
        return []
    
    print(f"    🔗 Agrupando {len(artigos_processados)} artigos por similaridade...")
    
    grupos = []
    artigos_visitados = set()
    
    for i, artigo in enumerate(artigos_processados):
        if artigo.id in artigos_visitados:
            continue
        
        # Cria novo grupo
        grupo = [artigo]
        artigos_visitados.add(artigo.id)
        
        # Busca artigos similares
        if artigo.embedding:
            embedding_artigo = bytes_to_embedding(artigo.embedding)
            
            for j, outro_artigo in enumerate(artigos_processados):
                if (outro_artigo.id not in artigos_visitados and 
                    outro_artigo.embedding and
                    outro_artigo.tag == artigo.tag):  # Mesma tag
                    
                    embedding_outro = bytes_to_embedding(outro_artigo.embedding)
                    similaridade = calcular_similaridade_cosseno(embedding_artigo, embedding_outro)
                    
                    if similaridade > 0.7:  # Threshold de similaridade
                        grupo.append(outro_artigo)
                        artigos_visitados.add(outro_artigo.id)
        
        grupos.append(grupo)
    
    print(f"    ✅ Criados {len(grupos)} grupos de notícias")
    return grupos

def main():
    """Função principal"""
    print("=" * 60)
    print("🔄 BTG AlphaFeed - Orquestrador (Fluxo de Negócio Correto)")
    print("=" * 60)
    
    # Configuração
    # Le flags: --stage 1|2|3|4|all ; --modo incremental|lote ; --limite N ; --day YYYY-MM-DD
    limite = 999
    modo_incremental = True
    stage = 'all'
    day_str: Optional[str] = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--stage' and i + 1 < len(args):
            stage = args[i + 1].lower()
        if arg == '--modo' and i + 1 < len(args):
            modo_incremental = (args[i + 1].lower() != 'lote')
        if arg == '--limite' and i + 1 < len(args):
            try:
                limite = int(args[i + 1])
            except Exception:
                pass
        if arg == '--day' and i + 1 < len(args):
            day_str = (args[i + 1] or "").strip() or None
    
    print(f"📊 Limite de artigos: {limite}")
    print(f"🎯 Modo: {'Incremental' if modo_incremental else 'Em Lote'}")
    print(f"🧭 Stage: {stage}")
    if day_str:
        print(f"📅 Filtro data: {day_str}")
    
    # Verifica configuração inicial
    print(f"🔧 GEMINI_API_KEY configurada: {'Sim' if os.getenv('GEMINI_API_KEY') else 'Não'}")
    print(f"🔧 DATABASE_URL configurada: {'Sim' if os.getenv('DATABASE_URL') else 'Não'}")
    
    # Execução por estágios
    sucesso = True
    if stage in ('1', 'all'):
        if modo_incremental:
            print(f"🎯 Modo INCREMENTAL: processar_artigos_pendentes(limite={limite}, day_str={day_str})")
            sucesso = processar_artigos_pendentes(limite=limite, day_str=day_str)
        else:
            print(f"🎯 Modo EM LOTE: processar_artigos_em_lote(limite={limite})")
            sucesso = processar_artigos_em_lote(limite)
        if not sucesso and stage != 'all':
            print("❌ Falhou na Etapa 1")
            return

    if stage in ('2', 'all') and sucesso:
        # A Etapa 2 já é executada dentro do fluxo de Etapa 1 no incremental/em lote.
        # Quando chamada isoladamente, apenas informa.
        print("ℹ️ Etapa 2 é executada automaticamente após a Etapa 1 neste orquestrador.")

    if stage in ('3', 'all') and sucesso:
        # A Etapa 3 é executada dentro de processar_artigos_pendentes após a 2.
        print("ℹ️ Etapa 3 é executada automaticamente após a Etapa 2 neste orquestrador.")

    if stage in ('4', 'all') and sucesso:
        # ETAPA 4 ja e executada dentro de processar_artigos_pendentes()
        # Chamar novamente aqui seria redundante e desperdicaria tokens do LLM.
        # So executa se stage='4' isoladamente (debug).
        if stage == '4':
            print(f"\n🔄 ETAPA 4: consolidacao_final_clusters()")
            print(f"📝 Usando prompt: PROMPT_CONSOLIDACAO_CLUSTERS_V1")
            ok2 = consolidacao_final_clusters(SessionLocal(), client)
            sucesso = ok2
        else:
            print("ℹ️ Etapa 4 já foi executada dentro do fluxo incremental.")
    
    if sucesso:
        print("\n🎉 Processamento completo concluído com sucesso!")
        print("💡 Verifique o frontend para ver os clusters e resumos gerados")
    else:
        print("\n❌ Processamento falhou")
    
    # =====================================================================
    # v2.0 - MODO SOMBRA DESATIVADO (Graph-RAG agora integrado ao pipeline)
    # 
    # A partir da v2.0 integrada, o enriquecimento Graph-RAG (embeddings,
    # entidades, grafo, contexto historico) acontece DENTRO das ETAPAs 1-4:
    #   ETAPA 1: gera embedding_v2 + extrai entidades + persiste no grafo
    #   ETAPA 2: usa similaridade cosseno para dicas de agrupamento
    #   ETAPA 3: injeta contexto historico do grafo no prompt de resumo
    #   ETAPA 4: usa similaridade entre clusters para sugestoes de merge
    #
    # O modo sombra original fica disponivel para debug/comparacao:
    #   V2_SHADOW_MODE=1 python process_articles.py
    # =====================================================================
    if os.getenv("V2_SHADOW_MODE", "0") == "1":
        print("\n[v2.0 SHADOW] Modo sombra ativado manualmente (V2_SHADOW_MODE=1)")
        try:
            from backend.workflow import run_batch_workflow
            db_shadow = SessionLocal()
            try:
                hoje = get_date_brasil_str()
                artigos_hoje = (
                    db_shadow.query(ArtigoBruto.id)
                    .filter(
                        ArtigoBruto.status == 'processado',
                        func.date(ArtigoBruto.processed_at) == hoje,
                    )
                    .order_by(ArtigoBruto.processed_at.desc())
                    .all()
                )
                artigo_ids = [a.id for a in artigos_hoje]
                print(f"  v2.0 SHADOW: {len(artigo_ids)} artigos para processar")
            finally:
                db_shadow.close()
            
            if artigo_ids:
                results = run_batch_workflow(artigo_ids=artigo_ids, shadow_mode=True, verbose=True)
        except Exception as e:
            print(f"  v2.0 SHADOW: Erro (nao critico): {e}")
    
    # Sumario do grafo (sempre mostra)
    try:
        from backend.agents.graph_crud import get_entity_stats
        db_stats = SessionLocal()
        try:
            stats = get_entity_stats(db_stats)
            print(f"\n  GRAFO v2: {stats.get('total_entities', 0)} entidades, "
                  f"{stats.get('total_edges', 0)} arestas, "
                  f"tipos: {stats.get('entities_by_type', {})}")
        finally:
            db_stats.close()
    except Exception:
        pass
    
    print("=" * 60)

if __name__ == "__main__":
    main() 