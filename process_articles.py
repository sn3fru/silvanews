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
from backend.prompts import PROMPT_AGRUPAMENTO_V1, PROMPT_RESUMO_FINAL_V3, PROMPT_PRIORIZACAO_EXECUTIVA_V1
from backend.utils import get_date_brasil_str, get_datetime_brasil_str

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
load_dotenv(env_file)
print(f"SUCESSO: Arquivo .env carregado: {env_file}")

# Configuração de lotes para evitar truncamento
BATCH_SIZE_AGRUPAMENTO = 150  # Lote maior para aumentar consolidação por fato

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
    Extrai e decodifica um objeto JSON de uma string de resposta do LLM,
    com um fluxo de tentativas robusto e simplificado.
    """
    import json
    import re

    if not isinstance(resposta, str) or not resposta.strip():
        print("❌ ERRO: Resposta da API está vazia.")
        return None

    print(f"🔍 Processando resposta de {len(resposta)} caracteres...")
    
    json_str = ""
    # Tenta extrair de um bloco de código markdown primeiro, que é o formato mais confiável.
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', resposta, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        print(f"📋 JSON extraído de bloco de código: {len(json_str)} caracteres")
    else:
        # Se não houver bloco de código, busca pelo início de um objeto ou array.
        start_pos = resposta.find('[')
        if start_pos == -1:
            start_pos = resposta.find('{')
        
        if start_pos != -1:
            json_str = resposta[start_pos:].strip()
            print(f"📋 JSON extraído por marcador de início: {len(json_str)} caracteres")
        else:
            print("❌ ERRO: Nenhum marcador de início de JSON ('[' ou '{') encontrado na resposta.")
            return None

    # --- FLUXO DE TENTATIVAS DE PARSING ---

    # TENTATIVA 1: Parse Direto
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"⚠️ Falha na Tentativa 1 (Parse Direto): {e}")

    # TENTATIVA 2: Extrair a Parte Válida (para JSONs truncados)
    json_parcial = extrair_json_valido(json_str)
    if json_parcial:
        print(f"🔧 Tentativa 2 (Extração Parcial) obteve um JSON de {len(json_parcial)} caracteres.")
        try:
            return json.loads(json_parcial)
        except json.JSONDecodeError as e:
            print(f"⚠️ Falha na Tentativa 2 mesmo após extração parcial: {e}")

    # TENTATIVA 3: Correção de Strings (como último recurso)
    json_corrigido = corrigir_json_strings(json_str)
    if json_corrigido != json_str:
        print(f"🔧 Tentativa 3 (Correção de Strings) alterou o JSON para {len(json_corrigido)} caracteres.")
        try:
            return json.loads(json_corrigido)
        except json.JSONDecodeError as e:
            print(f"⚠️ Falha na Tentativa 3 mesmo após correção: {e}")

    print("❌ ERRO FINAL: Todas as tentativas de extrair um JSON válido falharam.")
    print(f"📋 Primeiros 500 caracteres da resposta problemática: {resposta[:500]}...")
    return None

def corrigir_json_strings(json_str: str) -> str:
    """
    Realiza correções básicas e seguras em uma string JSON.
    O foco é remover caracteres inválidos e garantir que o escape de aspas
    seja consistente, sem tentar adivinhar o conteúdo de strings truncadas.
    """
    import re
    
    # 1. Remove caracteres de controle ASCII, exceto os comuns como \n, \r, \t.
    # Isso limpa "lixo" invisível que quebra o parser.
    json_corrigido = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
    
    # 2. Garante que barras invertidas que não são parte de uma sequência de escape válida
    # sejam escapadas. Ex: "caminho\no_arquivo" -> "caminho\\no_arquivo"
    # Isso evita erros de "invalid escape sequence".
    # A expressão (?!["\\/bfnrtu]) é um "negative lookahead", garantindo que não vamos
    # escapar barras que já fazem parte de uma sequência válida.
    json_corrigido = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_corrigido)
    
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

def processar_artigos_pendentes(limite: int = 10) -> bool:
    """
    Processa artigos pendentes seguindo o fluxo de negócio correto:
    1. Processa TODAS as notícias pendentes (extração de dados)
    2. Cria clusters/agrupamentos por fato gerador usando prompt de agrupamento
    3. Classifica prioridade e gera resumos seletivos
    """
    db = SessionLocal()
    try:
        # Busca artigos pendentes
        artigos_pendentes = get_artigos_pendentes(db, limite=limite)
        
        if not artigos_pendentes:
            print("SUCESSO: Nenhum artigo pendente encontrado")
            return True
        
        print(f"ARTIGOS: Encontrados {len(artigos_pendentes)} artigos pendentes")
        
        # Estatísticas do banco
        total_artigos = db.query(ArtigoBruto).count()
        artigos_processados = db.query(ArtigoBruto).filter(ArtigoBruto.status == "processado").count()
        artigos_erro = db.query(ArtigoBruto).filter(ArtigoBruto.status == "erro").count()
        clusters_existentes = db.query(ClusterEvento).count()
        
        print(f"ESTATISTICAS: Total artigos: {total_artigos}, Processados: {artigos_processados}, Erros: {artigos_erro}, Clusters: {clusters_existentes}")
        
        # ETAPA 1: Processar TODAS as notícias pendentes
        print(f"\nETAPA 1: Processando {len(artigos_pendentes)} artigos pendentes...")
        
        sucessos = 0
        erros = 0
        
        for i, artigo in enumerate(artigos_pendentes, 1):
            print(f"  PROCESSANDO: Artigo {i}/{len(artigos_pendentes)} (ID: {artigo.id})...")
            
            # Usa a função do backend para processar cada artigo (SEM clusterização)
            if processar_artigo_sem_cluster(db, artigo.id, client):
                sucessos += 1
                print(f"    SUCESSO: Artigo {artigo.id} processado")
            else:
                erros += 1
                print(f"    ERRO: Falha no processamento do artigo {artigo.id}")
            
            time.sleep(0.1)  # Pausa leve entre processamentos (throttle)
        
        print(f"ETAPA 1 CONCLUIDA: Sucessos: {sucessos}, Erros: {erros}")
        
        # ETAPA 2: Agrupamento inteligente com pivot automático
        print(f"\nETAPA 2: Agrupamento inteligente com pivot automático...")
        
        # Verifica se há clusters existentes hoje para decidir o modo
        hoje = get_date_brasil_str()
        clusters_existentes = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.status == 'ativo'
        ).count()
        
        if clusters_existentes > 0:
            # Modo incremental: anexa a clusters existentes
            print(f"🎯 MODO INCREMENTAL: {clusters_existentes} clusters existentes encontrados")
            sucesso_agrupamento = agrupar_noticias_incremental(db, client)
        else:
            # Modo em lote: cria clusters do zero
            print("🎯 MODO EM LOTE: Nenhum cluster existente, criando do zero")
            sucesso_agrupamento = agrupar_noticias_com_prompt(db, client)
        
        if sucesso_agrupamento:
            print("ETAPA 2 CONCLUIDA: Agrupamento realizado com sucesso")
        else:
            print("ETAPA 2 FALHOU: Erro no agrupamento")
            return False
        
        # ETAPA 3: Classificar e gerar resumos usando prompts
        print(f"\nETAPA 3: Classificando clusters e gerando resumos...")
        
        # Busca apenas clusters ativos hoje que NÃO têm resumo (novos)
        hoje = get_date_brasil_str()
        clusters_hoje = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            ClusterEvento.created_at >= hoje,
            ClusterEvento.resumo_cluster.is_(None)  # Apenas clusters sem resumo
        ).all()
        
        resumos_gerados = 0
        
        for cluster in clusters_hoje:
            print(f"  📝 Processando cluster {cluster.id}: '{cluster.titulo_cluster}'")
            
            # Classifica o cluster usando prompts do prompts.py
            if classificar_e_resumir_cluster(db, cluster.id, client):
                resumos_gerados += 1
                print(f"    ✅ Cluster {cluster.id} - Classificado e resumido")
            else:
                print(f"    ❌ Cluster {cluster.id} - Falha na classificação")
        
        print(f"ETAPA 3 CONCLUIDA: Resumos gerados: {resumos_gerados}")

        # ETAPA 4: Priorização Executiva Final (reclassificação rígida)
        print(f"\nETAPA 4: Priorização Executiva Final...")
        if priorizacao_executiva_final(db, client):
            print("ETAPA 4 CONCLUIDA: Priorização executiva aplicada")
        else:
            print("ETAPA 4 FALHOU: Erro na priorização executiva")
        
        # Resumo final
        print(f"\nPROCESSAMENTO CONCLUIDO:")
        print(f"  Artigos processados: {sucessos}")
        print(f"  Resumos gerados: {resumos_gerados}")
        print(f"  Priorização executiva: concluída")
        
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
    Mapeia as tags do prompt para as tags válidas do modelo.
    Agora as tags são as mesmas, então só retorna a tag original.
    """
    # As tags do prompt já são as mesmas do modelo
    return tag_prompt

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
    Classifica e resume um cluster usando os prompts do prompts.py.
    Esta função usa o PROMPT_EXTRACAO_PERMISSIVO_V8 para classificar o cluster
    e depois gera o resumo apropriado baseado na prioridade.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            if debug:
                print(f"    ❌ DEBUG: Cluster {cluster_id} não encontrado")
            return False
        
        artigos = get_artigos_by_cluster(db, cluster_id)
        if not artigos:
            if debug:
                print(f"    ❌ DEBUG: Nenhum artigo encontrado para cluster {cluster_id}")
            return False
        
        if debug:
            print(f"    🔍 DEBUG: Cluster {cluster_id} tem {len(artigos)} artigos")
        
        # Coleta todos os textos dos artigos para análise
        textos = []
        for i, artigo in enumerate(artigos):
            if artigo.texto_processado:
                texto_artigo = f"FONTE: {artigo.jornal or 'Desconhecida'}\n{artigo.texto_processado}"
                textos.append(texto_artigo)
                if debug:
                    print(f"    📄 DEBUG: Artigo {i+1}: {artigo.titulo_extraido or 'Sem título'}")
                    print(f"    📄 DEBUG: Texto: {artigo.texto_processado[:100]}...")
        
        texto_completo = "\n\n".join(textos)
        
        if debug:
            print(f"    📝 DEBUG: Texto completo para análise ({len(texto_completo)} chars):")
            print(f"    {'='*50}")
            print(texto_completo[:500] + "..." if len(texto_completo) > 500 else texto_completo)
            print(f"    {'='*50}")
        
        # Usa o prompt de extração para classificar o cluster
        from backend.prompts import PROMPT_EXTRACAO_PERMISSIVO_V8
        
        prompt_classificacao = f"""
        {PROMPT_EXTRACAO_PERMISSIVO_V8}
        
        NOTÍCIA PARA ANÁLISE:
        {texto_completo}
        
        Analise esta notícia e retorne a classificação conforme o guia acima.
        """
        
        if debug:
            print(f"    🤖 DEBUG: Enviando prompt para Gemini...")
            print(f"    🤖 DEBUG: Tamanho do prompt: {len(prompt_classificacao)} chars")
            print(f"    🤖 DEBUG: Primeiros 300 chars do prompt:")
            print(f"    {'='*50}")
            print(prompt_classificacao[:300] + "...")
            print(f"    {'='*50}")
        
        response = client.generate_content(
            prompt_classificacao,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 1024
            }
        )
        
        if not response.text:
            if debug:
                print(f"    ❌ DEBUG: API retornou resposta vazia para cluster {cluster_id}")
            return False
        
        if debug:
            print(f"    🤖 DEBUG: Resposta do Gemini ({len(response.text)} chars):")
            print(f"    {'='*50}")
            print(response.text)
            print(f"    {'='*50}")
        
        # Extrai JSON da resposta
        resultado = extrair_json_da_resposta(response.text)
        
        if debug:
            print(f"    🔍 DEBUG: Resultado extraído: {resultado}")
        
        # PRIMEIRO, verifica se a resposta é uma lista vazia, que significa "irrelevante"
        if isinstance(resultado, list) and len(resultado) == 0:
            if debug:
                print(f"    🚫 DEBUG: Notícia irrelevante detectada (API retornou lista vazia)")
            return marcar_cluster_irrelevante(db, cluster_id, debug)
        
        # DEPOIS, continua com a validação original para outros tipos de erro
        if not resultado or not isinstance(resultado, list):
            if debug:
                print(f"    ❌ DEBUG: Resposta inválida para cluster {cluster_id}")
                print(f"    ❌ DEBUG: Tipo do resultado: {type(resultado)}")
                print(f"    ❌ DEBUG: Conteúdo: {resultado}")
            return False
        
        # Pega o primeiro resultado (deveria ser só um)
        classificacao = resultado[0]
        
        if debug:
            print(f"    ✅ DEBUG: Classificação extraída: {classificacao}")
        
        # Atualiza o cluster com a classificação
        prioridade_original = cluster.prioridade
        tag_original = cluster.tag
        
        cluster.prioridade = classificacao.get('prioridade', 'P3_MONITORAMENTO')
        cluster.tag = mapear_tag_prompt_para_modelo(classificacao.get('tag', 'Sem categoria'))
        
        if debug:
            print(f"    🔄 DEBUG: Prioridade: {prioridade_original} → {cluster.prioridade}")
            print(f"    🔄 DEBUG: Tag: {tag_original} → {cluster.tag}")
        
        # Gera resumo baseado na prioridade usando função unificada
        prioridade = cluster.prioridade
        
        # Mapeia prioridade para nível de detalhe
        mapa_niveis = {
            'P1_CRITICO': 'Executivo (P1_CRITICO)',
            'P2_ESTRATEGICO': 'Padrão (P2_ESTRATEGICO)',
            'P3_MONITORAMENTO': 'Conciso (P3_MONITORAMENTO)'
        }
        
        nivel_detalhe = mapa_niveis.get(prioridade)
        if nivel_detalhe:
            if debug:
                print(f"    📝 DEBUG: Gerando resumo {prioridade} com nível {nivel_detalhe}...")
            
            if gerar_resumo_unificado(db, cluster_id, client, nivel_detalhe):
                print(f"    📝 {prioridade}: Resumo gerado com sucesso")
            else:
                print(f"    ❌ Falha ao gerar resumo {prioridade}")
                return False
        else:
            if debug:
                print(f"    ⚠️ DEBUG: Prioridade {prioridade} não mapeada para nível de detalhe")
        
        # Salva as mudanças
        db.commit()
        
        if debug:
            print(f"    ✅ DEBUG: Cluster {cluster_id} salvo com sucesso")
        
        return True
        
    except Exception as e:
        print(f"❌ ERRO: Falha ao classificar e resumir cluster {cluster_id}: {e}")
        if debug:
            import traceback
            traceback.print_exc()
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
        
        # Extrai JSON da resposta
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

        itens_finais = []
        id_map = {}
        for idx, c in enumerate(clusters_hoje):
            itens_finais.append({
                "id": idx,
                "cluster_id": c.id,
                "titulo_final": c.titulo_cluster,
                "prioridade_atribuida_inicial": c.prioridade,
                "tag_atribuida_inicial": c.tag,
                "score_inicial": None,
                "resumo_final": (c.resumo_cluster or "")[:1200]
            })
            id_map[idx] = c.id

        prompt = PROMPT_PRIORIZACAO_EXECUTIVA_V1.format(
            ITENS_FINAIS=json.dumps(itens_finais, indent=2, ensure_ascii=False)
        )

        if debug:
            print(f"🧮 DEBUG: Enviando priorização executiva para {len(itens_finais)} itens...")

        response = client.generate_content(
            prompt,
            generation_config={
                'temperature': 0.1,
                'top_p': 0.8,
                'max_output_tokens': 2048
            }
        )

        if not response.text:
            if debug:
                print("❌ Priorização executiva: resposta vazia")
            return False

        resultado = extrair_json_da_resposta(response.text)
        if not isinstance(resultado, list):
            if debug:
                print("❌ Priorização executiva: formato inválido")
            return False

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

                # Atualiza prioridade se diferente
                if decisao and decisao != cluster.prioridade:
                    update_cluster_priority(db, cluster_id, decisao, motivo=justificativa or "priorização executiva")
                    alteracoes += 1

                # Atualiza tag se fornecida e válida
                if tag and tag != cluster.tag:
                    update_cluster_tags(db, cluster_id, [tag], motivo="priorização executiva")
                    alteracoes += 1
            except Exception:
                continue

        if debug:
            print(f"✅ Priorização executiva concluída. Alterações aplicadas: {alteracoes}")
        return True

    except Exception as e:
        print(f"❌ ERRO: Priorização executiva falhou: {e}")
        return False

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
        
        print(f"🔗 AGRUPAMENTO INCREMENTAL: {len(artigos_novos)} artigos novos, {len(clusters_existentes)} clusters existentes")
        
        # Determina se precisa processar em lotes
        TAMANHO_LOTE_MAXIMO = 150  # Máximo de notícias por lote (incremental mais abrangente)
        processar_em_lotes = len(artigos_novos) > TAMANHO_LOTE_MAXIMO
        
        if processar_em_lotes:
            print(f"📦 PROCESSAMENTO EM LOTES: {len(artigos_novos)} notícias divididas em lotes de {TAMANHO_LOTE_MAXIMO}")
            
            # Divide artigos em lotes
            lotes = [artigos_novos[i:i + TAMANHO_LOTE_MAXIMO] for i in range(0, len(artigos_novos), TAMANHO_LOTE_MAXIMO)]
            
            total_anexacoes = 0
            total_novos_clusters = 0
            
            for i, lote in enumerate(lotes, 1):
                print(f"\n📦 PROCESSANDO LOTE {i}/{len(lotes)} ({len(lote)} notícias)...")
                
                sucesso_lote = processar_lote_incremental(db, client, lote, clusters_existentes, i)
                
                if sucesso_lote:
                    anexacoes, novos_clusters = sucesso_lote
                    total_anexacoes += anexacoes
                    total_novos_clusters += novos_clusters
                    print(f"✅ LOTE {i} CONCLUIDO: {anexacoes} anexações, {novos_clusters} novos clusters")
                else:
                    print(f"❌ LOTE {i} FALHOU")
                    return False
            
            print(f"🎉 AGRUPAMENTO INCREMENTAL CONCLUIDO: {total_anexacoes} anexações, {total_novos_clusters} novos clusters")
            
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
        
        print(f"📤 ENVIANDO LOTE {numero_lote}: {len(novas_noticias)} notícias para análise incremental...")
        
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
            
            print(f"📥 RESPOSTA RECEBIDA LOTE {numero_lote}: {len(response.text)} caracteres")
            
            # Extrai JSON da resposta
            classificacoes = extrair_json_da_resposta(response.text)
            
            if not classificacoes or not isinstance(classificacoes, list):
                print("❌ ERRO: Resposta de agrupamento incremental inválida")
                print(f"📋 Resposta recebida: {response.text[:500]}...")
                return False
            
            print(f"✅ SUCESSO LOTE {numero_lote}: {len(classificacoes)} classificações recebidas")
            
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
                            print(f"  ✅ Anexado: '{artigo.titulo_extraido}' → Cluster {cluster_existente.id}")
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
                        print(f"  ✅ Novo Cluster: '{tema_principal}' com '{artigo.titulo_extraido}'")
                    
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
        
        print(f"🔗 INICIANDO AGRUPAMENTO: {len(artigos_para_agrupar)} artigos a serem processados em lotes de {BATCH_SIZE_AGRUPAMENTO}.")
        
        # Mapeamento de ID para artigo original para todo o conjunto
        mapa_id_para_artigo = {i: artigo for i, artigo in enumerate(artigos_para_agrupar)}
        
        # Divide a lista de artigos em lotes
        lotes = [artigos_para_agrupar[i:i + BATCH_SIZE_AGRUPAMENTO] for i in range(0, len(artigos_para_agrupar), BATCH_SIZE_AGRUPAMENTO)]
        
        clusters_criados_total = 0
        artigos_agrupados_total = 0

        for num_lote, lote_artigos in enumerate(lotes, 1):
            print(f"\n--- Processando Lote {num_lote}/{len(lotes)} ({len(lote_artigos)} artigos) ---")
            
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
                grupos_brutos = extrair_json_da_resposta(response.text)
                
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
                        
                        print(f"  ✅ Grupo: '{tema_principal}' - {len(artigos_do_grupo)} artigos")
                        
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
            print(f"    📄 Artigo já estruturado, usando metadados existentes")
            
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
            # Para PDFs ou artigos sem estrutura, faz extração básica
            print(f"    📄 Artigo sem estrutura, fazendo extração básica")
            
            # Extração básica sem LLM
            linhas = artigo.texto_bruto.split('\n')
            titulo = linhas[0].strip() if linhas else "Sem título"
            
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
        
        # ETAPA 3: Validação com Pydantic
        try:
            print(f"    🔍 Validando dados com Pydantic...")
            
            noticia_obj = Noticia(**noticia_data)
            noticia_validada = noticia_obj.model_dump()
            print(f"    ✅ Validação Pydantic bem-sucedida")
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
        
        # Atualiza dados processados e marca como "pronto_agrupar"
        update_artigo_dados_sem_status(db, id_artigo, dados_processados, embedding_artigo)
        
        # Marca como pronto para agrupamento (status mais curto)
        update_artigo_status(db, id_artigo, "pronto_agrupar")
        
        # NÃO faz clusterização aqui - será feita na ETAPA 2
        
        create_log(db, "INFO", "processor", 
                  f"Artigo {id_artigo} pronto para agrupamento")
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
    limite = 999  # Limite para desenvolvimento
    modo_incremental = True  # True = incremental, False = em lote
    
    print(f"📊 Limite de artigos: {limite}")
    print(f"🎯 Modo: {'Incremental' if modo_incremental else 'Em Lote'}")
    
    # Verifica configuração inicial
    print(f"🔧 GEMINI_API_KEY configurada: {'Sim' if os.getenv('GEMINI_API_KEY') else 'Não'}")
    print(f"🔧 DATABASE_URL configurada: {'Sim' if os.getenv('DATABASE_URL') else 'Não'}")
    
    # Executa processamento
    if modo_incremental:
        sucesso = processar_artigos_pendentes(limite)
    else:
        sucesso = processar_artigos_em_lote(limite)
    
    if sucesso:
        print("\n🎉 Processamento completo concluído com sucesso!")
        print("💡 Verifique o frontend para ver os clusters e resumos gerados")
    else:
        print("\n❌ Processamento falhou")
    
    print("=" * 60)

if __name__ == "__main__":
    main() 