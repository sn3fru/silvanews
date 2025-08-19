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
    processar_artigo_pipeline, gerar_resumo_cluster, find_or_create_cluster
)
from backend.prompts import PROMPT_AGRUPAMENTO_V1, PROMPT_RESUMO_FINAL_V3, PROMPT_PRIORIZACAO_EXECUTIVA_V1, TAGS_SPECIAL_SITUATIONS
from backend.prompts import PROMPT_CONSOLIDACAO_CLUSTERS_V1
from backend.utils import get_date_brasil_str, get_datetime_brasil_str, corrigir_tag_invalida, corrigir_prioridade_invalida, eh_lixo_publicitario

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
load_dotenv(env_file)
print(f"SUCESSO: Arquivo .env carregado: {env_file}")

# Configuração de lotes para evitar truncamento
BATCH_SIZE_AGRUPAMENTO = 150  # Mais conservador para garantir respostas completas do LLM

# Configuração do Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERRO: GEMINI_API_KEY não configurada")
    sys.exit(1)

genai.configure(api_key=api_key)
client = genai.GenerativeModel('gemini-2.0-flash')
print("SUCESSO: Gemini configurado com sucesso!")

def extrair_json_da_resposta(resposta: str) -> Any:
    """
    Extrai e repara JSON de forma robusta a partir da resposta do LLM.
    Inclui sanitização de strings (aspas, quebras de linha) e fechamento
    balanceado de colchetes/chaves quando possível. Mantém fallback por regex.
    """
    import json
    import re

    def _extrair_bloco_json(texto: str) -> str:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Sem bloco: pega a partir de '[' ou '{'
        start_pos = texto.find('[')
        if start_pos == -1:
            start_pos = texto.find('{')
        return texto[start_pos:].strip() if start_pos != -1 else ""

    def _print_json_error_details(stage: str, text: str, err: Exception) -> None:
        try:
            import json as _json
            if isinstance(err, _json.JSONDecodeError):
                print(f"🧩 {stage}: {err.msg} (linha {err.lineno}, coluna {err.colno}, pos {err.pos})")
                pos = err.pos
                start = max(pos - 120, 0)
                end = min(pos + 120, len(text))
                trecho = text[start:end]
                print("--- Trecho próximo ao erro ---")
                print(trecho)
                caret_pos = pos - start
                if 0 <= caret_pos <= len(trecho):
                    print(" " * max(caret_pos, 0) + "^")
                if 0 <= pos < len(text):
                    ch = text[pos]
                    print(f"Caractere no erro: '{ch}' (ord={ord(ch)})")
                print("------------------------------")
        except Exception as _:
            pass

    def _sanitizar_json_like(json_like: str) -> str:
        # Remove backticks residuais e caracteres de controle invisíveis
        json_like = json_like.replace('```', '')
        json_like = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_like)

        # Passo estado: escapa quebras de linha CR/LF dentro de strings
        resultado = []
        in_str = False
        backslash_run = 0
        for ch in json_like:
            if in_str:
                if ch == '"' and backslash_run % 2 == 0:
                    in_str = False
                    resultado.append(ch)
                    backslash_run = 0
                    continue
                if ch == '\n':
                    # já é escape literal
                    resultado.append(ch)
                elif ch == '\r':
                    resultado.append('\\r')
                elif ch == '\n':
                    resultado.append('\\n')
                elif ch in ['\n', '\r']:
                    # segurança extra (ambiente pode entregar real newline)
                    if ch == '\n':
                        resultado.append('\\n')
                    else:
                        resultado.append('\\r')
                else:
                    # Acumula o char
                    resultado.append(ch)
                backslash_run = backslash_run + 1 if ch == '\\' else 0
            else:
                if ch == '"' and backslash_run % 2 == 0:
                    in_str = True
                if ch not in ['\x00', '\x0b', '\x0c']:
                    resultado.append(ch)
                backslash_run = backslash_run + 1 if ch == '\\' else 0
        sanitizado = ''.join(resultado)

        # Remove vírgulas finais antes de ']' ou '}'
        sanitizado = re.sub(r',\s*([}\]])', r'\1', sanitizado)

        # Balanceamento simples de colchetes/chaves
        def _balancear(s: str, abre: str, fecha: str) -> str:
            dif = s.count(abre) - s.count(fecha)
            if dif > 0:
                s += fecha * dif
            return s
        sanitizado = _balancear(sanitizado, '[', ']')
        sanitizado = _balancear(sanitizado, '{', '}')
        return sanitizado

    if not isinstance(resposta, str) or not resposta.strip():
        print("❌ ERRO: Resposta da API está vazia.")
        return None

    print(f"🔍 Processando resposta de {len(resposta)} caracteres...")

    bruto = _extrair_bloco_json(resposta)
    if not bruto:
        print("❌ ERRO: Nenhum marcador de início de JSON ('[' ou '{') encontrado na resposta.")
        return None

    # 1) Parse direto
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        _print_json_error_details("Falha na Tentativa 1 (Parse Direto)", bruto, e)

    # 2) Sanitização agressiva
    reparado = _sanitizar_json_like(bruto)
    try:
        return json.loads(reparado)
    except json.JSONDecodeError as e:
        _print_json_error_details("Falha após sanitização", reparado, e)

    # 3) Corte no último fechamento válido
    try:
        last_close = max(reparado.rfind('}'), reparado.rfind(']'))
        if last_close != -1:
            truncado = reparado[:last_close + 1]
            # Fecha array se foi iniciado como array
            if truncado.strip().startswith('[') and truncado.strip().count('[') > truncado.strip().count(']'):
                truncado += ']'
            return json.loads(truncado)
    except json.JSONDecodeError as e:
        _print_json_error_details("Falha no parse truncado", truncado if 'truncado' in locals() else reparado, e)

    print("❌ ERRO FINAL: Todas as tentativas de extrair um JSON válido falharam.")
    print(f"📋 Primeiros 500 caracteres da resposta problemática: {resposta[:500]}...")

    # 4) Fallback mínimo por regex (prioridade/tag)
    fallback = extrair_campos_minimos_por_regex(resposta)
    if fallback is not None:
        print("🔁 Fallback: Extração mínima via regex aplicada com sucesso.")
        return fallback

    return None

# ---------------- GATING EXPLÍCITO (REGRAS DETERMINÍSTICAS) -----------------
def _aplicar_gating_explicito_cluster(db: Session, cluster_id: int, debug: bool = True) -> None:
    """
    Aplica regras determinísticas para evitar classificações absurdas:
    - Conteúdos astrológicos/horóscopo/espiritualidade/autoajuda/psicologia-pop => IRRELEVANTE
    - Se tag for 'M&A e Transações Corporativas' e não houver gatilhos de M&A no texto, rebaixa prioridade para P3
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            return
        artigos = get_artigos_by_cluster(db, cluster_id)
        texto_total = " ".join([
            (a.titulo_extraido or "") + " " + (a.texto_processado or "") for a in artigos
        ]) + " " + (cluster.titulo_cluster or "") + " " + (cluster.resumo_cluster or "")

        # 1) Bloqueio de astrologia/horóscopo/espiritualidade/autoajuda
        padrao_bloqueio = re.compile(r"\b(hor[oó]scopo|astrolog|zod[ií]aco|signo[s]?|mapa\s+astral|tar[oô]|vident|numerolog|mercurio\s+retr[oó]grado)\b", re.IGNORECASE)
        if padrao_bloqueio.search(texto_total):
            if debug:
                print(f"    🚫 GATING: Cluster {cluster_id} marcado IRRELEVANTE (astrologia/horóscopo detectado)")
            cluster.prioridade = "IRRELEVANTE"
            cluster.tag = "IRRELEVANTE"
            cluster.resumo_cluster = "Conteúdo irrelevante (astrologia/horóscopo/espiritualidade) para a mesa de Special Situations"
            db.commit()
            return

        # 2) Validação de M&A (necessita gatilhos explícitos)
        if (cluster.tag or "").strip() == 'M&A e Transações Corporativas':
            padrao_ma = re.compile(r"\b(aquisi[cç][aã]o|compra|venda\s+de\s+ativo[s]?|divestiture|f(us[aã]o|us[oã])|incorpora[cç][aã]o|opa\b|oferta\s+p(ú|u)blica\s+de\s+aquisi[cç][aã]o|joint\s+venture|desinvestimento|alien[aá]c[aã]o|acordo\s+(vinculante|definitivo|assinado)|memorando\s+de\s+entendimento|negocia[cç][aã]o\s+exclusiva)\b", re.IGNORECASE)
            if not padrao_ma.search(texto_total):
                if cluster.prioridade in ("P1_CRITICO", "P2_ESTRATEGICO"):
                    if debug:
                        print(f"    ⚖️ GATING: Rebaixando Cluster {cluster_id} (M&A sem gatilho) → P3_MONITORAMENTO")
                    cluster.prioridade = "P3_MONITORAMENTO"
                    db.commit()
    except Exception as _e:
        if debug:
            print(f"    ⚠️ GATING: Falha ao aplicar regras para cluster {cluster_id}: {_e}")


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
        bruto = extrair_json_da_resposta(resposta)
        if isinstance(bruto, list):
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
        bruto = extrair_json_da_resposta(resposta)
        if isinstance(bruto, list):
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
        return None
    except Exception as e:
        print(f"❌ ERRO: Fallback incremental falhou: {e}")
        return None

def processar_artigos_pendentes(limite: int = 10) -> bool:
    """
    Fluxo em estágios com sincronização entre etapas e paralelismo onde seguro:
    1) ETAPA 1 (paralela): processa TODAS as notícias pendentes
    2) ETAPA 2 (síncrona): agrupamento (incremental ou em lote)
    3) ETAPA 3 (paralela): classificar clusters e gerar resumos
    4) ETAPA 4 (síncrona): priorização executiva e consolidação final; re-sumariza se necessário
    """
    db = SessionLocal()
    try:
        artigos_pendentes = get_artigos_pendentes(db, limite=limite)
        if not artigos_pendentes:
            print("SUCESSO: Nenhum artigo pendente encontrado")
            return True

        print(f"ARTIGOS: Encontrados {len(artigos_pendentes)} artigos pendentes")

        total_artigos = db.query(ArtigoBruto).count()
        artigos_processados = db.query(ArtigoBruto).filter(ArtigoBruto.status == "processado").count()
        artigos_erro = db.query(ArtigoBruto).filter(ArtigoBruto.status == "erro").count()
        clusters_existentes_count = db.query(ClusterEvento).count()
        print(f"ESTATISTICAS: Total artigos: {total_artigos}, Processados: {artigos_processados}, Erros: {artigos_erro}, Clusters: {clusters_existentes_count}")

        # ETAPA 1 — paralela
        print(f"\nETAPA 1: Processando {len(artigos_pendentes)} artigos pendentes em paralelo...")
        def _worker_proc(id_artigo: int) -> bool:
            _db = SessionLocal()
            try:
                return processar_artigo_sem_cluster(_db, id_artigo, client)
            finally:
                _db.close()

        max_workers = min(8, max(2, (os.cpu_count() or 4)))
        sucessos = 0
        erros = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_worker_proc, art.id): art.id for art in artigos_pendentes}
            for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                try:
                    if fut.result():
                        sucessos += 1
                    else:
                        erros += 1
                except Exception:
                    erros += 1
                if i % 10 == 0 or i == len(futures):
                    print(f"  Progresso ETAPA 1: {i}/{len(futures)} | ok={sucessos} err={erros}")

        print(f"ETAPA 1 CONCLUIDA: Sucessos: {sucessos}, Erros: {erros}")
        if sucessos == 0 and len(artigos_pendentes) > 0:
            print("❌ Nenhum artigo processado com sucesso. Abortando.")
            return False

        # ETAPA 2 — síncrona
        print(f"\nETAPA 2: Agrupamento inteligente com pivot automático...")
        hoje = get_date_brasil_str()
        clusters_existentes_hoje = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.status == 'ativo'
        ).count()
        if clusters_existentes_hoje > 0:
            print(f"🎯 MODO INCREMENTAL: {clusters_existentes_hoje} clusters existentes encontrados")
            sucesso_agrupamento = agrupar_noticias_incremental(db, client)
        else:
            print("🎯 MODO EM LOTE: Nenhum cluster existente, criando do zero")
            sucesso_agrupamento = agrupar_noticias_com_prompt(db, client)
        if not sucesso_agrupamento:
            print("ETAPA 2 FALHOU: Erro no agrupamento")
            return False
        print("ETAPA 2 CONCLUIDA: Agrupamento realizado com sucesso")

        # ETAPA 3 — paralela
        print(f"\nETAPA 3: Classificando clusters e gerando resumos em paralelo...")
        clusters_hoje = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            ClusterEvento.created_at >= hoje,
            ClusterEvento.resumo_cluster.is_(None)
        ).all()

        def _worker_classificar(cid: int) -> bool:
            _db = SessionLocal()
            try:
                return classificar_e_resumir_cluster(_db, cid, client, debug=False)
            finally:
                _db.close()

        resumos_gerados = 0
        if clusters_hoje:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(_worker_classificar, c.id): c.id for c in clusters_hoje}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        if fut.result():
                            resumos_gerados += 1
                    except Exception:
                        pass
        print(f"ETAPA 3 CONCLUIDA: Resumos gerados: {resumos_gerados}")

        # ETAPA 4 — síncrona
        print(f"\nETAPA 4: Priorização executiva e consolidação final de clusters...")
        ok_prior = priorizacao_executiva_final(SessionLocal(), client)
        ok_cons = consolidacao_final_clusters(SessionLocal(), client)
        if not (ok_prior and ok_cons):
            print("⚠️ Etapa 4 concluída com avisos (alguma parte falhou)")
        else:
            print("ETAPA 4 CONCLUIDA: Priorização/Consolidação aplicadas")

        # Re-sumariza clusters que ainda ficaram sem resumo após consolidação
        db2 = SessionLocal()
        try:
            pendentes = db2.query(ClusterEvento).filter(
                ClusterEvento.status == 'ativo',
                ClusterEvento.created_at >= hoje,
                ClusterEvento.resumo_cluster.is_(None)
            ).all()
        finally:
            db2.close()
        if pendentes:
            print(f"Re-sumariando {len(pendentes)} clusters sem resumo após a consolidação...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(_worker_classificar, c.id): c.id for c in pendentes}
                for _ in concurrent.futures.as_completed(futures):
                    pass

        print(f"\nPROCESSAMENTO CONCLUIDO:")
        print(f"  Artigos processados: {sucessos}")
        print(f"  Resumos gerados: {resumos_gerados}")
        print(f"  Etapa 4 executada: {'sim' if (ok_prior and ok_cons) else 'parcial'}")
        return True

    except Exception as e:
        print(f"ERRO: Erro geral no processamento: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

def mapear_tag_prompt_para_modelo(tag_prompt: str) -> str:
    """
    Normaliza uma tag retornada pelo LLM para uma tag CANÔNICA presente em TAGS_SPECIAL_SITUATIONS.
    - Faz match case-insensitive com as chaves de TAGS_SPECIAL_SITUATIONS.
    - Se não bater, tenta corrigir via corrigir_tag_invalida.
    - Fallback seguro: 'Internacional (Economia e Política)'.
    """
    try:
        valid_tags = list(TAGS_SPECIAL_SITUATIONS.keys())
        if not isinstance(tag_prompt, str) or not tag_prompt.strip():
            return 'Internacional (Economia e Política)'

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
        return 'Internacional (Economia e Política)'
    except Exception:
        return 'Internacional (Economia e Política)'

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

def classificar_e_resumir_cluster(db: Session, cluster_id: int, client, debug: bool = True) -> bool:
    """
    Classifica e resume um cluster com lógica de retentativa robusta:
    - Tentativa 1: artigo âncora + títulos
    - Tentativa 2: apenas títulos (super leve)
    - Falha geral: marca como P3_REVISAR (erro controlado)
    """
    try:
        from backend.prompts import PROMPT_EXTRACAO_GATEKEEPER_V13 as _PROMPT

        cluster = get_cluster_by_id(db, cluster_id)
        artigos = get_artigos_by_cluster(db, cluster_id)
        if not cluster or not artigos:
            return False

        print(f"[Cluster {cluster_id}] {len(artigos)} notícias")
        vistos = set()
        for i, artigo in enumerate(artigos):
            titulo_base = (artigo.titulo_extraido or artigo.texto_processado or "").replace("\n", " ").strip()[:100]
            if titulo_base and titulo_base not in vistos:
                vistos.add(titulo_base)
                print(f"  - {i+1}. {titulo_base}")

        # Preparos
        artigo_ancora = max(artigos, key=lambda a: len(a.texto_processado or ""))
        outros_titulos = [f"- {a.titulo_extraido or 'N/A'} (Fonte: {a.jornal or 'N/A'})" for a in artigos if a.id != artigo_ancora.id]

        def _chamar(prompt: str, max_tokens: int = 2048):
            return client.generate_content(prompt, generation_config={'temperature': 0.1, 'top_p': 0.9, 'max_output_tokens': max_tokens})

        # Tentativa 1: âncora + títulos
        try:
            texto_anchor = (artigo_ancora.texto_processado or "")
            bloco = f"ARTIGO PRINCIPAL:\nTítulo: {artigo_ancora.titulo_extraido or 'N/A'}\nFonte: {artigo_ancora.jornal or 'N/A'}\nTexto: {texto_anchor}\n\nTITULOS ADICIONAIS DO MESMO GRUPO:\n" + ("\n".join(outros_titulos) if outros_titulos else "Nenhum")
            prompt_1 = f"{_PROMPT}\n\nNOTÍCIA PARA ANÁLISE:\n{bloco}"
            if debug:
                print(f"    🤖 Tentativa 1 (âncora+títulos) len={len(prompt_1)}")
            resp1 = _chamar(prompt_1, max_tokens=4096)
            resultado = extrair_json_da_resposta(resp1.text or "")
        except Exception as e1:
            if debug:
                print(f"    ⚠️ Tentativa 1 falhou: {e1}")
            resultado = None

        # Tentativa 2: apenas títulos
        if not resultado or (isinstance(resultado, list) and len(resultado) == 0):
            try:
                titulos_todos = [f"- {a.titulo_extraido or 'N/A'} (Fonte: {a.jornal or 'N/A'})" for a in artigos]
                bloco2 = "TÍTULOS DAS NOTÍCIAS DO GRUPO:\n" + "\n".join(titulos_todos)
                prompt_2 = f"{_PROMPT}\n\nNOTÍCIA PARA ANÁLISE (APENAS TÍTULOS):\n{bloco2}"
                if debug:
                    print(f"    🤖 Tentativa 2 (títulos) len={len(prompt_2)}")
                resp2 = _chamar(prompt_2, max_tokens=2048)
                resultado = extrair_json_da_resposta(resp2.text or "")
            except Exception as e2:
                if debug:
                    print(f"    ❌ Tentativa 2 falhou: {e2}")
                return marcar_cluster_como_erro(db, cluster_id, "Falha em ambas as tentativas de classificação")

        if debug:
            if isinstance(resultado, list):
                if len(resultado) > 0 and isinstance(resultado[0], dict):
                    _t = (resultado[0].get('titulo') or '')[:140]
                    _rr = (resultado[0].get('relevance_reason') or '')[:200]
                    print(f"    🔍 Extração OK: titulo='{_t}' | relevance_reason='{_rr}'")
                else:
                    print("    🔍 Extração: lista vazia")
            else:
                print(f"    🔍 Extração: tipo inválido ({type(resultado)})")

        if isinstance(resultado, list) and len(resultado) == 0:
            return marcar_cluster_irrelevante(db, cluster_id, debug)
        if not resultado or not isinstance(resultado, list) or not resultado[0]:
            return marcar_cluster_como_erro(db, cluster_id, "Resposta final inválida")

        classificacao = resultado[0]
        faltando = [k for k in ("titulo", "prioridade", "tag") if not classificacao.get(k)]
        if faltando:
            print(f"  ⚠️ Campos ausentes no resultado: {', '.join(faltando)}")

        prioridade_sugerida = corrigir_prioridade_invalida(classificacao.get('prioridade'))
        if prioridade_sugerida == 'IRRELEVANTE':
            return marcar_cluster_irrelevante(db, cluster_id, debug)

        cluster.prioridade = prioridade_sugerida
        cluster.tag = mapear_tag_prompt_para_modelo(classificacao.get('tag', 'Sem categoria'))
        print(f"  => Classificação: {cluster.prioridade} | Tag: {cluster.tag}")

        mapa_niveis = {
            'P1_CRITICO': 'Executivo (P1_CRITICO)',
            'P2_ESTRATEGICO': 'Padrão (P2_ESTRATEGICO)',
            'P3_MONITORAMENTO': 'Conciso (P3_MONITORAMENTO)'
        }
        nivel_detalhe = mapa_niveis.get(cluster.prioridade, 'Conciso (P3_MONITORAMENTO)')
        if gerar_resumo_unificado(db, cluster_id, client, nivel_detalhe):
            print(f"    📝 {cluster.prioridade}: Resumo gerado com sucesso")
        else:
            print(f"    ❌ Falha ao gerar resumo {cluster.prioridade}")
            # Mantém classificação mesmo sem resumo

        db.commit()

        # GATING determinístico pós-classificação para evitar absurdos (ex.: horóscopo como P1 M&A)
        _aplicar_gating_explicito_cluster(db, cluster_id, debug)
        # Correção determinística de TAG para casos de Dívida Ativa/CDA
        _corrigir_tag_deterministica_cluster(db, cluster_id, debug)
        return True

    except Exception as e:
        print(f"❌ ERRO: Falha ao classificar e resumir cluster {cluster_id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        if debug:
            import traceback
            traceback.print_exc()
        return marcar_cluster_como_erro(db, cluster_id, str(e))

def marcar_cluster_como_erro(db: Session, cluster_id: int, motivo: str) -> bool:
    try:
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
    Gera um resumo para um cluster com um nível de detalhe variável.
    Usa o PROMPT_RESUMO_FINAL_V3 para consistência.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            return False
        
        artigos = get_artigos_by_cluster(db, cluster_id)
        if not artigos:
            return False
        
        # Coleta todos os textos dos artigos
        textos = []
        for artigo in artigos:
            if artigo.texto_processado:
                textos.append(f"FONTE: {artigo.jornal or 'Desconhecida'}\n{artigo.texto_processado}")
        
        texto_completo = "\n\n".join(textos)
        
        # Prepara dados do cluster para o prompt
        dados_do_grupo = {
            "tema_principal": cluster.titulo_cluster,
            "categoria": cluster.tag,
            "prioridade": cluster.prioridade,
            "noticias": [
                {
                    "titulo": artigo.titulo_extraido or "Sem título",
                    "texto": artigo.texto_processado or "",
                    "jornal": artigo.jornal or "Fonte desconhecida"
                }
                for artigo in artigos
            ]
        }
        
        # Usa o PROMPT_RESUMO_FINAL_V3 importado de prompts.py
        prompt_completo = PROMPT_RESUMO_FINAL_V3.format(
            NIVEL_DE_DETALHE=nivel_detalhe,
            DADOS_DO_GRUPO=json.dumps(dados_do_grupo, indent=2, ensure_ascii=False)
        )
        
        response = client.generate_content(
            prompt_completo,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 2048 if nivel_detalhe == 'Executivo (P1_CRITICO)' else 512
            }
        )
        
        if not response.text:
            return False
        
        # Extrai JSON da resposta (robusto)
        resultado_json = extrair_json_da_resposta(response.text)
        
        if resultado_json and 'resumo_final' in resultado_json:
            # Remove o título "Resumo Executivo:" se ele aparecer
            resumo_limpo = resultado_json['resumo_final']
            if ': ' in resumo_limpo:
                resumo_limpo = resumo_limpo.split(': ', 1)[1]
            
            cluster.resumo_cluster = resumo_limpo
            db.commit()
            return True
        
        return False
        
    except Exception as e:
        print(f"ERRO: Falha ao gerar resumo unificado para cluster {cluster_id}: {e}")
        return False


def priorizacao_executiva_final(db: Session, client, debug: bool = True) -> bool:
    """
    Aplica a priorização executiva (pós-agrupamento e pós-resumo) usando
    PROMPT_PRIORIZACAO_EXECUTIVA_V1 sobre os clusters ativos do dia.
    Reclassifica prioridade, ajusta score (se armazenado futuramente) e registra alterações.
    """
    try:
        hoje = get_date_brasil_str()
        clusters_hoje = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            ClusterEvento.created_at >= hoje
        ).all()

        if not clusters_hoje:
            if debug:
                print("ℹ️ Priorização executiva: nenhum cluster ativo hoje")
            return True

        # Decide estratégia: usa batching direto quando muitos itens, senão tenta one-shot
        itens_finais_all = []
        id_map_all = {}
        for idx, c in enumerate(clusters_hoje):
            itens_finais_all.append({
                "id": idx,
                "cluster_id": c.id,
                "titulo_final": c.titulo_cluster,
                "prioridade_atribuida_inicial": c.prioridade,
                "tag_atribuida_inicial": c.tag,
                "score_inicial": None,
                "resumo_final": (c.resumo_cluster or "")[:400]
            })
            id_map_all[idx] = c.id

        TAMANHO_LOTE_PRIORIZACAO = 60
        usar_one_shot = len(itens_finais_all) <= TAMANHO_LOTE_PRIORIZACAO

        if usar_one_shot:
            prompt_all = PROMPT_PRIORIZACAO_EXECUTIVA_V1.format(
                ITENS_FINAIS=json.dumps(itens_finais_all, indent=2, ensure_ascii=False)
            )

            if debug:
                print(f"🧮 DEBUG: Priorização one-shot para {len(itens_finais_all)} itens...")

            try:
                resp_all = client.generate_content(
                    prompt_all,
                    generation_config={
                        'temperature': 0.1,
                        'top_p': 0.8,
                        'max_output_tokens': 8192
                    }
                )
            except Exception as e:
                if debug:
                    print(f"❌ Priorização one-shot falhou na chamada: {e}")
                resp_all = None

            if resp_all and resp_all.text:
                if debug:
                    prev = resp_all.text[:500].replace('\n', ' ')
                    print(f"📥 Priorização one-shot (prev 500): {prev}")
                resultado_all = extrair_json_da_resposta(resp_all.text)
                if not isinstance(resultado_all, list) or len(resultado_all) == 0:
                    resultado_all = extrair_priorizacao_executiva_seguro(resp_all.text)
                # Se veio uma lista mas sem 'id', faz fallback regex
                if isinstance(resultado_all, list) and resultado_all and not any(isinstance(it, dict) and it.get('id') is not None for it in resultado_all):
                    resultado_all = extrair_priorizacao_executiva_seguro(resp_all.text)
                if isinstance(resultado_all, list) and len(resultado_all) > 0:
                    alteracoes = 0
                    for item in resultado_all:
                        try:
                            rid = item.get("id")
                            decisao = item.get("decisao_prioridade_final")
                            tag = item.get("tag_final") or item.get("tag_atribuida_inicial")
                            justificativa = item.get("justificativa_executiva")
                            cid = id_map_all.get(rid)
                            if cid is None:
                                continue
                            cluster = get_cluster_by_id(db, cid)
                            if not cluster:
                                continue
                            if decisao and decisao != cluster.prioridade:
                                update_cluster_priority(db, cid, decisao, motivo=justificativa or "priorização executiva")
                                alteracoes += 1
                            if tag and tag != cluster.tag:
                                update_cluster_tags(db, cid, [tag], motivo="priorização executiva")
                                alteracoes += 1
                        except Exception:
                            continue
                    if debug:
                        print(f"✅ Priorização executiva (one-shot) aplicada. Alterações: {alteracoes}")
                    return True

        # Batching dos itens para evitar truncamento e JSON quebrado
        lotes = [clusters_hoje[i:i + TAMANHO_LOTE_PRIORIZACAO] for i in range(0, len(clusters_hoje), TAMANHO_LOTE_PRIORIZACAO)]

        alteracoes_total = 0
        for idx, lote in enumerate(lotes, 1):
            itens_finais = []
            id_map = {}
            for j, c in enumerate(lote):
                itens_finais.append({
                    "id": j,
                    "cluster_id": c.id,
                    "titulo_final": c.titulo_cluster,
                    "prioridade_atribuida_inicial": c.prioridade,
                    "tag_atribuida_inicial": c.tag,
                    "score_inicial": None,
                    "resumo_final": (c.resumo_cluster or "")[:400]
                })
                id_map[j] = c.id

            prompt = PROMPT_PRIORIZACAO_EXECUTIVA_V1.format(
                ITENS_FINAIS=json.dumps(itens_finais, indent=2, ensure_ascii=False)
            )

            if debug:
                print(f"🧮 DEBUG: Lote priorização {idx}/{len(lotes)} com {len(itens_finais)} itens...")

            response = client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,
                    'top_p': 0.8,
                    'max_output_tokens': 4096
                }
            )

            if not response.text:
                if debug:
                    print(f"❌ Priorização executiva: resposta vazia no lote {idx}")
                continue

            if debug:
                prev = response.text[:500].replace('\n', ' ') if isinstance(response.text, str) else 'N/A'
                print(f"📥 Lote {idx} priorização (prev 500): {prev}")

            resultado = extrair_json_da_resposta(response.text)
            if not isinstance(resultado, list) or len(resultado) == 0:
                resultado = extrair_priorizacao_executiva_seguro(response.text)
            # Fallback adicional: lista sem 'id' útil
            if isinstance(resultado, list) and resultado and not any(isinstance(it, dict) and it.get('id') is not None for it in resultado):
                resultado = extrair_priorizacao_executiva_seguro(response.text)
            if not isinstance(resultado, list) or len(resultado) == 0:
                if debug:
                    print(f"ℹ️ Priorização executiva: nenhuma decisão válida no lote {idx}")
                continue

            alteracoes = 0
            for item in resultado:
                try:
                    rid = item.get("id")
                    decisao = item.get("decisao_prioridade_final")
                    tag = item.get("tag_final") or item.get("tag_atribuida_inicial")
                    justificativa = item.get("justificativa_executiva")

                    if rid is None or id_map.get(rid) is None:
                        continue
                    cluster_id = id_map[rid]
                    cluster = get_cluster_by_id(db, cluster_id)
                    if not cluster:
                        continue

                    if decisao and decisao != cluster.prioridade:
                        update_cluster_priority(db, cluster_id, decisao, motivo=justificativa or "priorização executiva")
                        alteracoes += 1

                    if tag and tag != cluster.tag:
                        update_cluster_tags(db, cluster_id, [tag], motivo="priorização executiva")
                        alteracoes += 1
                except Exception:
                    continue

            alteracoes_total += alteracoes

        if debug:
            print(f"✅ Priorização executiva concluída. Alterações aplicadas (total): {alteracoes_total}")
        return True

    except Exception as e:
        print(f"❌ ERRO: Priorização executiva falhou: {e}")
        return False


def consolidacao_final_clusters(db: Session, client, debug: bool = True) -> bool:
    """
    Etapa 4 (reagrupamento): Consolida clusters redundantes do dia com base em títulos, tags e prioridades já definidas.
    - Prepara uma lista de clusters do dia (exclui IRRELEVANTE e sem prioridade/tag)
    - Envia para o prompt de consolidação pedindo sugestões de merges/keeps
    - Aplica merges conservadores via utilitário de merge no CRUD
    """
    try:
        hoje = get_date_brasil_str()
        # Seleciona clusters ativos do dia, excluindo irrelevantes
        clusters = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            ClusterEvento.created_at >= hoje,
            ClusterEvento.prioridade != 'IRRELEVANTE',
            ClusterEvento.tag != 'IRRELEVANTE'
        ).all()

        if not clusters:
            if debug:
                print("ℹ️ Consolidação final: nenhum cluster elegível hoje")
            return True

        # Monta payload leve por cluster
        itens = []
        for c in clusters:
            # Títulos internos (curtos) para dar contexto
            arts = get_artigos_by_cluster(db, c.id)
            titulos_internos = [(a.titulo_extraido or (a.texto_processado or '')[:80]) for a in arts[:4]]
            itens.append({
                "id": c.id,
                "titulo": c.titulo_cluster,
                "tag": c.tag,
                "prioridade": c.prioridade,
                "titulos_internos": titulos_internos
            })

        from backend.crud import merge_clusters, update_cluster_title, update_cluster_priority, update_cluster_tags

        # ONE-SHOT: tenta enviar todos os clusters de uma vez com max tokens; se falhar, fallback para lotes (código abaixo)
        prompt_all = PROMPT_CONSOLIDACAO_CLUSTERS_V1.format(
            CLUSTERS_DO_DIA=json.dumps(itens, indent=2, ensure_ascii=False)
        )
        if debug:
            print(f"🧩 Consolidação one-shot: enviando {len(itens)} clusters")
        try:
            resp_all = client.generate_content(
                prompt_all,
                generation_config={'temperature': 0.1, 'top_p': 0.8, 'max_output_tokens': 8192}
            )
        except Exception as e:
            if debug:
                print(f"❌ Consolidação one-shot falhou na chamada: {e}")
            resp_all = None

        if resp_all and resp_all.text:
            if debug:
                prev = resp_all.text[:500].replace('\n', ' ')
                print(f"📥 Consolidação one-shot (prev 500): {prev}")
            sugestoes_all = extrair_sugestoes_consolidacao_seguro(resp_all.text)
            if isinstance(sugestoes_all, list) and len(sugestoes_all) > 0:
                merges_aplicados_total = 0
                keeps_total = 0
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
                            merge_clusters(
                                db,
                                destino_id=int(destino),
                                fontes_ids=[int(x) for x in fontes if isinstance(x, (int, str))],
                                novo_titulo=novo_titulo,
                                nova_tag=nova_tag,
                                nova_prioridade=corigir_prioridade(nova_prioridade) if nova_prioridade else None,
                                motivo='consolidação etapa 4'
                            )
                            merges_aplicados_total += 1
                    except Exception:
                        continue
                if debug:
                    print(f"✅ Consolidação final (one-shot) aplicada. merges={merges_aplicados_total}, keeps={keeps_total}")
                # NÃO retorna aqui; segue para fallback determinístico para capturar duplicatas residuais

        # Fallback: Processa em lotes para evitar respostas truncadas
        TAMANHO_LOTE_CONSOLIDACAO = 80
        lotes = [itens[i:i + TAMANHO_LOTE_CONSOLIDACAO] for i in range(0, len(itens), TAMANHO_LOTE_CONSOLIDACAO)]

        merges_aplicados_total = 0
        keeps_total = 0

        for idx, lote in enumerate(lotes, 1):
            prompt = PROMPT_CONSOLIDACAO_CLUSTERS_V1.format(
                CLUSTERS_DO_DIA=json.dumps(lote, indent=2, ensure_ascii=False)
            )

            if debug:
                print(f"🧩 Consolidação: enviando lote {idx}/{len(lotes)} com {len(lote)} clusters")

            response = client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,
                    'top_p': 0.8,
                    'max_output_tokens': 8192
                }
            )

            if not response.text:
                if debug:
                    print(f"❌ Consolidação: resposta vazia no lote {idx}")
                continue

            if debug:
                prev = response.text[:500].replace('\n', ' ') if isinstance(response.text, str) else 'N/A'
                print(f"📥 Lote {idx} resposta (prev 500): {prev}")

            sugestoes = extrair_sugestoes_consolidacao_seguro(response.text)
            if not isinstance(sugestoes, list) or not sugestoes:
                if debug:
                    print(f"ℹ️ Consolidação: nenhuma sugestão válida no lote {idx} — aplicando fallback estrito por título/tag")
                # Fallback: de-duplicação ultra-conservadora por título normalizado + mesma tag
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
                    # mapa por (norm_title, tag)
                    grupos = {}
                    for it in lote:
                        chave = (_norm(it.get('titulo') or ''), it.get('tag'))
                        if not chave[0] or not chave[1]:
                            continue
                        grupos.setdefault(chave, []).append(it)
                    merges_aplicados_fallback = 0
                    for (_, _tag), items in grupos.items():
                        if len(items) <= 1:
                            continue
                        # destino: menor id
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
                continue

            if debug:
                print(f"🔎 Lote {idx}: {len(sugestoes)} sugestões válidas")
                for ex in sugestoes[:2]:
                    try:
                        print(f"   ↪ exemplo: {json.dumps(ex)[:240]}")
                    except Exception:
                        pass

            merges_aplicados = 0
            keeps = 0
            for s in sugestoes:
                try:
                    if not isinstance(s, dict):
                        continue
                    tipo = (s.get('tipo') or '').lower()
                    if tipo == 'keep' and s.get('cluster_id'):
                        keeps += 1
                        continue
                    if tipo == 'merge':
                        destino = s.get('destino')
                        fontes = s.get('fontes') or []
                        novo_titulo = s.get('novo_titulo')
                        nova_tag = s.get('nova_tag')
                        nova_prioridade = s.get('nova_prioridade')

                        if not destino or not fontes:
                            continue

                        merge_clusters(
                            db,
                            destino_id=int(destino),
                            fontes_ids=[int(x) for x in fontes if isinstance(x, (int, str))],
                            novo_titulo=novo_titulo,
                            nova_tag=nova_tag,
                            nova_prioridade=corigir_prioridade(nova_prioridade) if nova_prioridade else None,
                            motivo='consolidação etapa 4'
                        )
                        merges_aplicados += 1
                except Exception as e:
                    if debug:
                        try:
                            print(f"   ⚠️ Erro ao aplicar sugestão: {e} | item={json.dumps(s)[:240]}")
                        except Exception:
                            print(f"   ⚠️ Erro ao aplicar sugestão: {e}")
                    continue

            merges_aplicados_total += merges_aplicados
            keeps_total += keeps

        if debug:
            print(f"✅ Consolidação por sugestões aplicada. merges={merges_aplicados_total}, keeps={keeps_total}")

        # Passo final: Fallback determinístico SEM modelo para captar quase-duplicatas remanescentes
        try:
            if debug:
                print("🔁 Consolidação determinística por título/tag (pós-sugestões)...")
            # Recarrega clusters atuais do dia
            hoje2 = get_date_brasil_str()
            clusters2 = db.query(ClusterEvento).filter(
                ClusterEvento.status == 'ativo',
                ClusterEvento.created_at >= hoje2,
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
                    'prio': c.prioridade or 'P3_MONITORAMENTO'
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
        bruto = extrair_json_da_resposta(resposta)
        itens: List[Dict[str, Any]] = []
        if isinstance(bruto, list):
            for obj in bruto:
                if isinstance(obj, dict) and ('tipo' in obj):
                    itens.append(obj)
        if itens:
            return itens

        # Fallback por regex
        import re
        padrao_obj = re.compile(r"\{[\s\S]*?\}")
        candidatos = padrao_obj.findall(resposta)
        resultados: List[Dict[str, Any]] = []
        for cand in candidatos:
            try:
                texto = cand
                # Normaliza aspas/backticks
                texto = texto.replace('```', '')
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

                if item['tipo'] == 'merge':
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
                if item['tipo'] == 'merge' and (not item.get('destino') or not item.get('fontes')):
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

def agrupar_noticias_incremental(db: Session, client) -> bool:
    """
    Agrupamento incremental: anexa novas notícias a clusters existentes ou cria novos clusters.
    Usa o prompt PROMPT_AGRUPAMENTO_INCREMENTAL_V1 para decisão inteligente.
    Processa em lotes se houver muitas notícias para evitar truncamento.
    """
    try:
        # Busca artigos prontos para agrupamento que não foram associados a clusters
        hoje = get_date_brasil_str()
        artigos_novos = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.is_(None)  # Artigos não associados a clusters
        ).all()
        
        if not artigos_novos:
            print("INFO: Nenhum artigo novo encontrado para agrupamento incremental")
            return True
        
        # Busca clusters existentes criados hoje
        clusters_existentes = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.status == 'ativo'
        ).all()
        
        print(f"🔗 AGRUPAMENTO INCREMENTAL: {len(artigos_novos)} notícias novas, {len(clusters_existentes)} clusters existentes")
        
        # Determina se precisa processar em lotes
        TAMANHO_LOTE_MAXIMO = 200  # Máximo de notícias por lote (incremental mais abrangente)
        processar_em_lotes = len(artigos_novos) > TAMANHO_LOTE_MAXIMO
        
        if processar_em_lotes:
            print(f"📦 Lotes: {len(artigos_novos)} notícias em blocos de {TAMANHO_LOTE_MAXIMO}")
            
            # Divide artigos em lotes
            lotes = [artigos_novos[i:i + TAMANHO_LOTE_MAXIMO] for i in range(0, len(artigos_novos), TAMANHO_LOTE_MAXIMO)]
            
            total_anexacoes = 0
            total_novos_clusters = 0
            
            for i, lote in enumerate(lotes, 1):
                print(f"\n📦 Lote {i}/{len(lotes)} ({len(lote)} notícias)")
                
                sucesso_lote = processar_lote_incremental(db, client, lote, clusters_existentes, i)
                
                if sucesso_lote:
                    anexacoes, novos_clusters = sucesso_lote
                    total_anexacoes += anexacoes
                    total_novos_clusters += novos_clusters
                    print(f"✅ Lote {i}: {anexacoes} anexações, {novos_clusters} novos clusters")
                else:
                    print(f"❌ Lote {i} falhou")
                    return False
            
            print(f"🎉 Incremental concluído: {total_anexacoes} anexações, {total_novos_clusters} novos clusters")
            
            # Marca artigos como "processado" após clusterização
            marcar_artigos_processados(db, artigos_novos)
            
            return True
        else:
            # Processa tudo de uma vez (caso original)
            resultado = processar_lote_incremental(db, client, artigos_novos, clusters_existentes, 1)
            if resultado:
                # Marca artigos como "processado" após clusterização
                marcar_artigos_processados(db, artigos_novos)
            return resultado
        
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
    """
    try:
        # Prepara dados para o prompt incremental
        novas_noticias = []
        for i, artigo in enumerate(artigos_lote):
            noticia_data = {
                "id": i,
                "titulo": artigo.titulo_extraido or "Sem título"
            }
            novas_noticias.append(noticia_data)
        
        clusters_existentes_data = []
        for i, cluster in enumerate(clusters_existentes):
            artigos_cluster = get_artigos_by_cluster(db, cluster.id)
            titulos = [
                a.titulo_extraido or (a.texto_processado[:80] + "...") if (a.texto_processado or "") else "Sem título"
                for a in artigos_cluster
            ]
            titulos = titulos[:30]
            cluster_data = {
                "cluster_id": cluster.id,
                "tema_principal": cluster.titulo_cluster,
                "titulos_internos": titulos
            }
            clusters_existentes_data.append(cluster_data)
        
        # Mapeamento de ID para artigo original
        mapa_id_para_artigo = {i: artigo for i, artigo in enumerate(artigos_lote)}
        
        # Monta o prompt incremental
        from backend.prompts import PROMPT_AGRUPAMENTO_INCREMENTAL_V2
        prompt_completo = PROMPT_AGRUPAMENTO_INCREMENTAL_V2.format(
            NOVAS_NOTICIAS=json.dumps(novas_noticias, indent=2, ensure_ascii=False),
            CLUSTERS_EXISTENTES=json.dumps(clusters_existentes_data, indent=2, ensure_ascii=False)
        )
        print(f"📤 Enviando lote {numero_lote}: {len(novas_noticias)} notícias para análise...")
        
        # Chama a API para análise incremental
        try:
            response = client.generate_content(
                prompt_completo,
                generation_config={
                    'temperature': 0.1,  # Mais determinístico
                    'top_p': 0.8,
                    'max_output_tokens': 8192,  # Aumentado para lotes maiores
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
            
            for classificacao in classificacoes:
                try:
                    tipo = classificacao.get("tipo")
                    noticia_id = classificacao.get("noticia_id")
                    
                    if noticia_id not in mapa_id_para_artigo:
                        print(f"  ⚠️ ID de notícia inválido: {noticia_id}")
                        continue
                    
                    artigo = mapa_id_para_artigo[noticia_id]
                    
                    if tipo == "anexar":
                        # Anexa a cluster existente
                        cluster_id_existente = classificacao.get("cluster_id_existente")
                        cluster_existente = next((c for c in clusters_existentes if c.id == cluster_id_existente), None)
                        
                        if cluster_existente:
                            associate_artigo_to_cluster(db, artigo.id, cluster_existente.id)
                            anexacoes += 1
                            # Linha concisa, 100 chars
                            tprev = (artigo.titulo_extraido or artigo.texto_processado or "").replace("\n"," ")[:100]
                            print(f"  ✔ anexar: '{tprev}' → cluster {cluster_existente.id}")
                        else:
                            print(f"  ❌ Cluster {cluster_id_existente} não encontrado")
                    
                    elif tipo == "novo_cluster":
                        # Cria novo cluster
                        tema_principal = classificacao.get("tema_principal", f"Novo Cluster - {artigo.titulo_extraido}")
                        
                        # Calcula embedding do artigo
                        embedding_medio = None
                        if artigo.embedding:
                            embedding_medio = artigo.embedding
                        
                        # Cria cluster
                        from backend.models import ClusterEventoCreate
                        cluster_data = ClusterEventoCreate(
                            titulo_cluster=tema_principal,
                            resumo_cluster=None,  # Será preenchido na ETAPA 3
                            tag="Internacional (Economia e Política)",  # Padrão, será redefinido na ETAPA 3
                            prioridade="P3_MONITORAMENTO",  # Padrão, será redefinido na ETAPA 3
                            embedding_medio=embedding_medio
                        )
                        
                        cluster = create_cluster(db, cluster_data)
                        associate_artigo_to_cluster(db, artigo.id, cluster.id)
                        novos_clusters += 1
                        tprev = (artigo.titulo_extraido or artigo.texto_processado or "").replace("\n"," ")[:100]
                        print(f"  ✚ novo-cluster: '{tema_principal[:100]}' com '{tprev}'")
                    
                    else:
                        print(f"  ⚠️ Tipo de classificação inválido: {tipo}")
                
                except Exception as e:
                    print(f"  ❌ Erro ao processar classificação: {e}")
                    continue
            
            return (anexacoes, novos_clusters)
            
        except Exception as e:
            print(f"❌ ERRO na chamada da API incremental: {e}")
            return False
        
    except Exception as e:
        print(f"❌ ERRO: Falha no processamento do lote {numero_lote}: {e}")
        import traceback
        traceback.print_exc()
        return False


def agrupar_noticias_com_prompt(db: Session, client) -> bool:
    """
    Agrupa notícias usando prompt, agora processando em lotes (batches)
    para evitar truncamento de resposta da API com grandes volumes.
    """
    try:
        # Busca todas as notícias prontas para agrupamento
        artigos_para_agrupar = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.is_(None)
        ).all()
        
        if not artigos_para_agrupar:
            print("INFO: Nenhum artigo novo para agrupamento.")
            return True
        
        print(f"🔗 INICIANDO AGRUPAMENTO: {len(artigos_para_agrupar)} em lotes de {BATCH_SIZE_AGRUPAMENTO}.")
        
        # Mapeamento de ID para artigo original para todo o conjunto
        mapa_id_para_artigo = {i: artigo for i, artigo in enumerate(artigos_para_agrupar)}
        
        # Divide a lista de artigos em lotes
        lotes = [artigos_para_agrupar[i:i + BATCH_SIZE_AGRUPAMENTO] for i in range(0, len(artigos_para_agrupar), BATCH_SIZE_AGRUPAMENTO)]
        
        clusters_criados_total = 0
        artigos_agrupados_total = 0

        for num_lote, lote_artigos in enumerate(lotes, 1):
            print(f"\n--- Lote {num_lote}/{len(lotes)} ({len(lote_artigos)} artigos) ---")
            
            # Prepara dados apenas para o lote atual
            noticias_lote_para_prompt = []
            mapa_id_lote_para_artigo = {}
            for i, artigo in enumerate(lote_artigos):
                 # O 'id' aqui é relativo ao lote, para o prompt.
                noticia_data = {
                    "id": i,
                    "titulo": artigo.titulo_extraido or "Sem título",
                    "jornal": artigo.jornal or "Fonte desconhecida",
                    "trecho": (artigo.texto_processado[:150] + "...") if len(artigo.texto_processado or "") > 150 else (artigo.texto_processado or "")
                }
                noticias_lote_para_prompt.append(noticia_data)
                mapa_id_lote_para_artigo[i] = artigo # Mapeia o ID do lote para o objeto artigo completo

            # Monta o prompt completo para o lote
            prompt_completo = f"""
{PROMPT_AGRUPAMENTO_V1}

NOTÍCIAS PARA AGRUPAR (LOTE {num_lote}/{len(lotes)}):
{json.dumps(noticias_lote_para_prompt, indent=2, ensure_ascii=False)}

IMPORTANTE: Retorne APENAS o JSON válido para este lote.
"""
            
            print(f"📤 ENVIANDO Lote {num_lote} para a API...")
            
            try:
                # Chama a API para o lote
                response = client.generate_content(
                    prompt_completo,
                    generation_config={
                        'temperature': 0.05,  # Ainda mais determinístico
                        'top_p': 0.7,
                        'max_output_tokens': 8192,  # Reduzido para lotes menores
                        'candidate_count': 1,
                        'top_k': 10
                    }
                )
                
                if not response.text:
                    print(f"⚠️ AVISO: API retornou resposta vazia para o lote {num_lote}. Pulando este lote.")
                    continue
                
                print(f"📥 RESPOSTA RECEBIDA para o Lote {num_lote}: {len(response.text)} caracteres")
                
                # Usa a nova função de extração robusta
                grupos_brutos = extrair_grupos_agrupamento_seguro(response.text)
                
                if not grupos_brutos or not isinstance(grupos_brutos, list):
                    print(f"❌ ERRO: Resposta de agrupamento inválida para o lote {num_lote}.")
                    continue
                
                print(f"✅ SUCESSO LOTE {num_lote}: {len(grupos_brutos)} grupos criados.")
                
                # Processa os clusters do lote
                for grupo_data in grupos_brutos:
                    try:
                        tema_principal = grupo_data.get("tema_principal", f"Grupo Lote {num_lote}")
                        ids_no_lote = grupo_data.get("ids_originais", [])
                        artigos_do_grupo = [mapa_id_lote_para_artigo[id_lote] for id_lote in ids_no_lote if id_lote in mapa_id_lote_para_artigo]
                        
                        if not artigos_do_grupo:
                            continue
                        
                        # ETAPA 2: SÓ AGRUPA - usa valores padrão, serão redefinidos na ETAPA 3
                        prioridade_grupo = "P3_MONITORAMENTO"  # Padrão, será redefinido na ETAPA 3
                        tag_grupo = "Internacional (Economia e Política)"  # Padrão, será redefinido na ETAPA 3
                        
                        # Calcula embedding médio do grupo
                        embeddings = []
                        for artigo in artigos_do_grupo:
                            if artigo.embedding:
                                embeddings.append(bytes_to_embedding(artigo.embedding))
                        
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
                            embedding_medio=embedding_medio
                        )
                        
                        cluster = create_cluster(db, cluster_data)
                        clusters_criados_total += 1
                        
                        # Associa artigos ao cluster
                        for artigo in artigos_do_grupo:
                            associate_artigo_to_cluster(db, artigo.id, cluster.id)
                            artigos_agrupados_total += 1
                        
                        print(f"  ✅ Grupo: '{tema_principal[:100]}' - {len(artigos_do_grupo)} artigos")
                        
                    except Exception as e:
                        print(f"  ❌ Erro ao processar grupo no lote {num_lote}: {e}")
                        continue

            except Exception as e_lote:
                print(f"❌ ERRO CRÍTICO ao processar o lote {num_lote}: {e_lote}")
                continue # Pula para o próximo lote

        print(f"\n🎉 ETAPA 2 CONCLUÍDA: {clusters_criados_total} clusters criados, {artigos_agrupados_total} artigos agrupados no total.")
        
        # Marca artigos como "processado" após clusterização
        artigos_agrupados = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "pronto_agrupar",
            ArtigoBruto.cluster_id.isnot(None)  # Artigos que foram agrupados
        ).all()
        marcar_artigos_processados(db, artigos_agrupados)
        
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
                
                # Cria cluster com dados básicos
                cluster_data = ClusterEventoCreate(
                    titulo_cluster=f"Cluster {i} - {len(grupo)} notícias",
                    resumo_cluster=None,  # Será preenchido se necessário
                    tag=grupo[0].tag,
                    prioridade=prioridade_grupo,
                    embedding_medio=embedding_medio
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

            # Pré-filtro de lixo publicitário (curto-circuito)
            if eh_lixo_publicitario(titulo, artigo.texto_bruto):
                prev = (titulo or "").replace("\n"," ")[:120]
                print(f"    EXCLUIDO: LIXO_PUBLICITARIO (pré-migração) - '{prev}'")
                update_artigo_status(db, id_artigo, 'irrelevante')
                return True

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
        
        # Corrige a tag se necessário
        if 'tag' in noticia_data:
            noticia_data['tag'] = corrigir_tag_invalida(noticia_data['tag'])
        
        # Pré-filtro de lixo publicitário com dados migrados também (dupla checagem)
        if eh_lixo_publicitario(noticia_data.get('titulo'), noticia_data.get('texto_completo')):
            prev = (noticia_data.get('titulo') or "").replace("\n"," ")[:120]
            print(f"    EXCLUIDO: LIXO_PUBLICITARIO (pós-migração) - '{prev}'")
            update_artigo_status(db, id_artigo, 'irrelevante')
            return True

        # ETAPA 3: Validação com Pydantic
        try:
            noticia_obj = Noticia(**noticia_data)
            noticia_validada = noticia_obj.model_dump()
            # sucesso silencioso em validação
        except Exception as e:
            print(f"    ❌ Erro de validação Pydantic: {e}")
            create_log(db, "ERROR", "processor", 
                      f"Erro de validação Pydantic do artigo {id_artigo}: {e}")
            update_artigo_status(db, id_artigo, 'erro')
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
        
        # IMPORTANTE: Preserva o texto_bruto original e salva o processado separadamente
        # O texto_bruto NÃO deve ser alterado - é o conteúdo original do PDF/URL
        # O texto_processado deve ser um resumo real, não uma cópia do original
        
        # Gera um resumo real usando o LLM para o texto_processado
        try:
            from backend.prompts import PROMPT_RESUMO_FINAL_V3
            
            # Prepara dados para o prompt de resumo
            dados_para_resumo = {
                "tema_principal": noticia_validada['titulo'],
                "categoria": noticia_validada['categoria'],
                "prioridade": noticia_validada['prioridade'],
                "noticias": [
                    {
                        "titulo": noticia_validada['titulo'],
                        "texto": noticia_validada['texto_completo'],
                        "jornal": noticia_validada['jornal']
                    }
                ]
            }
            
            # Usa o prompt de resumo para gerar um resumo real
            prompt_resumo = PROMPT_RESUMO_FINAL_V3.format(
                NIVEL_DE_DETALHE="Conciso (P3_MONITORAMENTO)",
                DADOS_DO_GRUPO=json.dumps(dados_para_resumo, indent=2, ensure_ascii=False)
            )
            
            # Chama o LLM para gerar resumo
            response = client.generate_content(
                prompt_resumo,
                generation_config={
                    'temperature': 0.3,
                    'top_p': 0.9,
                    'max_output_tokens': 512
                }
            )
            
            if response.text:
                # Extrai o resumo da resposta
                resultado_json = extrair_json_da_resposta(response.text)
                if resultado_json and 'resumo_final' in resultado_json:
                    resumo_limpo = resultado_json['resumo_final']
                    if ': ' in resumo_limpo:
                        resumo_limpo = resumo_limpo.split(': ', 1)[1]
                    dados_processados['texto_completo'] = resumo_limpo
                    print(f"    📝 Resumo gerado: {len(resumo_limpo)} caracteres")
                else:
                    print(f"    ⚠️ Falha ao extrair resumo, mantendo texto original")
            else:
                print(f"    ⚠️ Falha ao gerar resumo, mantendo texto original")
                
        except Exception as e:
            print(f"    ⚠️ Erro ao gerar resumo: {e}, mantendo texto original")
            # Em caso de erro, mantém o texto original como processado
        
        # Atualiza dados processados e marca como "pronto_agrupar"
        update_artigo_dados_sem_status(db, id_artigo, dados_processados, embedding_artigo)
        
        # Marca como pronto para agrupamento (status mais curto)
        update_artigo_status(db, id_artigo, "pronto_agrupar")
        
        # NÃO faz clusterização aqui - será feita na ETAPA 2
        
        create_log(db, "INFO", "processor", 
                  f"Artigo {id_artigo} pronto para agrupamento")
        # Sucesso mínimo: imprime apenas o título
        titulo_ok = (noticia_validada['titulo'] or '').replace('\n',' ')[:140]
        print(f"    OK: '{titulo_ok}'")
        return True
        
    except Exception as e:
        print(f"    ❌ Erro geral no processamento: {e}")
        import traceback
        traceback.print_exc()
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
    # Le flags simples via args: --stage 1|2|3|4|all ; --modo incremental|lote ; --limite N
    limite = 999
    modo_incremental = True
    stage = 'all'
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
    
    print(f"📊 Limite de artigos: {limite}")
    print(f"🎯 Modo: {'Incremental' if modo_incremental else 'Em Lote'}")
    print(f"🧭 Stage: {stage}")
    
    # Verifica configuração inicial
    print(f"🔧 GEMINI_API_KEY configurada: {'Sim' if os.getenv('GEMINI_API_KEY') else 'Não'}")
    print(f"🔧 DATABASE_URL configurada: {'Sim' if os.getenv('DATABASE_URL') else 'Não'}")
    
    # Execução por estágios
    sucesso = True
    if stage in ('1', 'all'):
        if modo_incremental:
            sucesso = processar_artigos_pendentes(limite)
        else:
            sucesso = processar_artigos_em_lote(limite)
        if not sucesso and stage != 'all':
            print("\n❌ Falhou na Etapa 1")
            return

    if stage in ('2', 'all') and sucesso:
        # A Etapa 2 já é executada dentro do fluxo de Etapa 1 no incremental/em lote.
        # Quando chamada isoladamente, apenas informa.
        print("ℹ️ Etapa 2 é executada automaticamente após a Etapa 1 neste orquestrador.")

    if stage in ('3', 'all') and sucesso:
        # A Etapa 3 é executada dentro de processar_artigos_pendentes após a 2.
        print("ℹ️ Etapa 3 é executada automaticamente após a Etapa 2 neste orquestrador.")

    if stage in ('4', 'all') and sucesso:
        print("\nETAPA 4: Consolidação final de clusters...")
        ok = priorizacao_executiva_final(SessionLocal(), client)
        ok2 = consolidacao_final_clusters(SessionLocal(), client)
        sucesso = ok and ok2
    
    if sucesso:
        print("\n🎉 Processamento completo concluído com sucesso!")
        print("💡 Verifique o frontend para ver os clusters e resumos gerados")
    else:
        print("\n❌ Processamento falhou")
    
    print("=" * 60)

if __name__ == "__main__":
    main() 