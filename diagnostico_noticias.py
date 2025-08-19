#!/usr/bin/env python3
"""
DIAGNÓSTICO COMPLETO DO FLUXO DE NOTÍCIAS
==========================================

Este arquivo rastreia uma notícia específica através de TODAS as tabelas
para identificar onde está o problema com os dados raw.

USO:
    conda activate pymc2
    python diagnostico_noticias.py

SAÍDA:
    - Rastreamento completo de uma notícia com 3+ fontes
    - Verificação de todas as tabelas
    - Mapeamento do fluxo de dados
    - Identificação de problemas
"""

import sys
import os
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Optional

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Imports do backend
try:
    from dotenv import load_dotenv
    from sqlalchemy.orm import Session
    from sqlalchemy import func, text
    
    from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
    from backend.crud import (
        get_artigos_by_cluster, get_cluster_by_id, get_artigos_pendentes
    )
    
    print("✅ Módulos do backend importados com sucesso!")
except ImportError as e:
    print(f"❌ ERRO ao importar módulos: {e}")
    sys.exit(1)

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Arquivo .env carregado: {env_file}")
else:
    print("⚠️ Arquivo .env não encontrado")

def print_header(title: str, char: str = "=", width: int = 80):
    """Imprime cabeçalho formatado"""
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")

def print_section(title: str, char: str = "-", width: int = 60):
    """Imprime seção formatada"""
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")

def print_data(title: str, data: Any, max_length: int = 200):
    """Imprime dados formatados com limite de caracteres"""
    if isinstance(data, str):
        if len(data) > max_length:
            data_display = data[:max_length] + f"... [TRUNCADO - {len(data)} chars]"
        else:
            data_display = data
    else:
        data_display = str(data)
    
    print(f"📋 {title}:")
    print(f"   {data_display}")

def verificar_conexao_banco():
    """Verifica conexão com o banco de dados"""
    print_header("🔌 VERIFICAÇÃO DE CONEXÃO COM BANCO")
    
    try:
        db = SessionLocal()
        
        # Testa conexão básica
        result = db.execute(text("SELECT 1"))
        print("✅ Conexão com banco estabelecida")
        
        # Verifica tabelas principais
        tabelas = ['artigos_brutos', 'clusters_eventos']
        for tabela in tabelas:
            try:
                count = db.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar()
                print(f"✅ Tabela {tabela}: {count} registros")
            except Exception as e:
                print(f"❌ Erro ao acessar tabela {tabela}: {e}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ ERRO na conexão com banco: {e}")
        return False

def encontrar_noticia_com_multiplas_fontes():
    """Encontra uma notícia que tenha 3+ fontes para análise"""
    print_header("🔍 BUSCANDO NOTÍCIA COM MÚLTIPLAS FONTES")
    
    try:
        db = SessionLocal()
        
        # Busca clusters com 3+ artigos
        query = text("""
            SELECT 
                c.id as cluster_id,
                c.titulo_cluster,
                c.tag,
                c.prioridade,
                COUNT(a.id) as total_artigos,
                c.created_at
            FROM clusters_eventos c
            JOIN artigos_brutos a ON a.cluster_id = c.id
            WHERE c.status = 'ativo'
            GROUP BY c.id, c.titulo_cluster, c.tag, c.prioridade, c.created_at
            HAVING COUNT(a.id) >= 3
            ORDER BY c.created_at DESC
            LIMIT 5
        """)
        
        clusters = db.execute(query).fetchall()
        
        if not clusters:
            print("❌ Nenhum cluster com 3+ artigos encontrado")
            return None
        
        print(f"✅ Encontrados {len(clusters)} clusters com 3+ artigos:")
        for i, cluster in enumerate(clusters, 1):
            print(f"   {i}. Cluster {cluster.cluster_id}: '{cluster.titulo_cluster[:80]}'")
            print(f"      📰 {cluster.total_artigos} artigos | {cluster.tag} | {cluster.prioridade}")
            print(f"      📅 {cluster.created_at}")
        
        # Seleciona o primeiro para análise
        cluster_selecionado = clusters[0]
        print(f"\n🎯 SELECIONADO para análise: Cluster {cluster_selecionado.cluster_id}")
        
        db.close()
        return cluster_selecionado
        
    except Exception as e:
        print(f"❌ ERRO ao buscar notícia: {e}")
        return None

def analisar_cluster_completo(cluster_id: int):
    """Analisa um cluster completo com todos os seus artigos"""
    print_header(f"🔬 ANÁLISE COMPLETA DO CLUSTER {cluster_id}")
    
    try:
        db = SessionLocal()
        
        # 1. DADOS DO CLUSTER
        print_section("📊 DADOS DO CLUSTER")
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            print("❌ Cluster não encontrado")
            return
        
        print_data("ID do Cluster", cluster.id)
        print_data("Título", cluster.titulo_cluster)
        print_data("Tag", cluster.tag)
        print_data("Prioridade", cluster.prioridade)
        print_data("Status", cluster.status)
        print_data("Total de Artigos", cluster.total_artigos)
        print_data("Data de Criação", cluster.created_at)
        print_data("Data de Atualização", cluster.updated_at)
        
        if cluster.resumo_cluster:
            print_data("Resumo do Cluster", cluster.resumo_cluster, max_length=300)
        else:
            print("📝 Resumo do Cluster: NÃO DEFINIDO")
        
        # 2. ARTIGOS DO CLUSTER
        print_section("📰 ARTIGOS DO CLUSTER")
        artigos = get_artigos_by_cluster(db, cluster_id)
        print(f"✅ Encontrados {len(artigos)} artigos no cluster")
        
        for i, artigo in enumerate(artigos, 1):
            print(f"\n📄 ARTIGO {i}/{len(artigos)} (ID: {artigo.id})")
            print(f"   📋 Título Extraído: {artigo.titulo_extraido or 'N/A'}")
            print(f"   📰 Jornal: {artigo.jornal or 'N/A'}")
            print(f"   ✍️ Autor: {artigo.autor or 'N/A'}")
            print(f"   📄 Página: {artigo.pagina or 'N/A'}")
            print(f"   📅 Data Publicação: {artigo.data_publicacao or 'N/A'}")
            print(f"   🏷️ Tag: {artigo.tag or 'N/A'}")
            print(f"   ⚡ Prioridade: {artigo.prioridade or 'N/A'}")
            print(f"   📊 Status: {artigo.status or 'N/A'}")
            print(f"   🔗 Cluster ID: {artigo.cluster_id or 'N/A'}")
            print(f"   🕐 Criado em: {artigo.created_at or 'N/A'}")
            print(f"   📅 Processado em: {artigo.processed_at or 'N/A'}")
            
            # ANÁLISE DO TEXTO BRUTO
            if artigo.texto_bruto:
                print(f"   📖 TEXTO BRUTO:")
                print(f"      Tamanho: {len(artigo.texto_bruto)} caracteres")
                print(f"      Início: {artigo.texto_bruto[:150]}...")
                print(f"      Fim: ...{artigo.texto_bruto[-150:]}")
                
                # Verifica se parece ser texto original ou resumo
                if len(artigo.texto_bruto) > 1000:
                    print(f"      ✅ PARECE TEXTO ORIGINAL (longo: {len(artigo.texto_bruto)} chars)")
                else:
                    print(f"      ⚠️ PARECE RESUMO (curto: {len(artigo.texto_bruto)} chars)")
            else:
                print(f"   ❌ TEXTO BRUTO: NÃO DEFINIDO")
            
            # ANÁLISE DO TEXTO PROCESSADO
            if artigo.texto_processado:
                print(f"   📝 TEXTO PROCESSADO:")
                print(f"      Tamanho: {len(artigo.texto_processado)} caracteres")
                print(f"      Início: {artigo.texto_processado[:150]}...")
                print(f"      Fim: ...{artigo.texto_processado[-150:]}")
                
                # Verifica se parece ser resumo ou texto original
                if len(artigo.texto_processado) > 1000:
                    print(f"      ⚠️ PARECE TEXTO ORIGINAL (longo: {len(artigo.texto_processado)} chars)")
                else:
                    print(f"      ✅ PARECE RESUMO (curto: {len(artigo.texto_processado)} chars)")
            else:
                print(f"   ❌ TEXTO PROCESSADO: NÃO DEFINIDO")
            
            # COMPARAÇÃO TEXTOS
            if artigo.texto_bruto and artigo.texto_processado:
                if artigo.texto_bruto == artigo.texto_processado:
                    print(f"   🚨 PROBLEMA: texto_bruto e texto_processado são IDÊNTICOS!")
                elif len(artigo.texto_bruto) > len(artigo.texto_processado):
                    print(f"   ✅ OK: texto_bruto ({len(artigo.texto_bruto)}) > texto_processado ({len(artigo.texto_processado)})")
                else:
                    print(f"   ⚠️ ATENÇÃO: texto_processado ({len(artigo.texto_processado)}) > texto_bruto ({len(artigo.texto_bruto)})")
            
            # METADADOS
            if artigo.metadados:
                print(f"   🔧 METADADOS: {artigo.metadados}")
            else:
                print(f"   🔧 METADADOS: NÃO DEFINIDO")
            
            # EMBEDDING
            if artigo.embedding:
                print(f"   🧠 EMBEDDING: Definido ({len(artigo.embedding)} bytes)")
            else:
                print(f"   ❌ EMBEDDING: NÃO DEFINIDO")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ ERRO ao analisar cluster: {e}")
        import traceback
        traceback.print_exc()
        return False

def verificar_estrutura_tabelas():
    """Verifica a estrutura das tabelas principais"""
    print_header("🏗️ VERIFICAÇÃO DA ESTRUTURA DAS TABELAS")
    
    try:
        db = SessionLocal()
        
        # 1. ESTRUTURA ARTIGOS_BRUTOS
        print_section("📰 TABELA: artigos_brutos")
        query = text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'artigos_brutos'
            ORDER BY ordinal_position
        """)
        
        colunas = db.execute(query).fetchall()
        print("Colunas da tabela artigos_brutos:")
        for col in colunas:
            nullable = "NULL" if col.is_nullable == "YES" else "NOT NULL"
            default = f" DEFAULT {col.column_default}" if col.column_default else ""
            print(f"   {col.column_name}: {col.data_type} {nullable}{default}")
        
        # 2. ESTRUTURA CLUSTERS_EVENTOS
        print_section("📋 TABELA: clusters_eventos")
        query = text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'clusters_eventos'
            ORDER BY ordinal_position
        """)
        
        colunas = db.execute(query).fetchall()
        print("Colunas da tabela clusters_eventos:")
        for col in colunas:
            nullable = "NULL" if col.is_nullable == "YES" else "NOT NULL"
            default = f" DEFAULT {col.column_default}" if col.column_default else ""
            print(f"   {col.column_name}: {col.data_type} {nullable}{default}")
        
        db.close()
        
    except Exception as e:
        print(f"❌ ERRO ao verificar estrutura: {e}")

def verificar_estatisticas_gerais():
    """Verifica estatísticas gerais do banco"""
    print_header("📊 ESTATÍSTICAS GERAIS DO BANCO")
    
    try:
        db = SessionLocal()
        
        # Contagem por status
        query = text("""
            SELECT 
                status,
                COUNT(*) as total,
                COUNT(texto_bruto) as com_texto_bruto,
                COUNT(texto_processado) as com_texto_processado,
                AVG(LENGTH(texto_bruto)) as avg_tamanho_bruto,
                AVG(LENGTH(texto_processado)) as avg_tamanho_processado
            FROM artigos_brutos
            GROUP BY status
        """)
        
        stats = db.execute(query).fetchall()
        print("Estatísticas por status:")
        for stat in stats:
            print(f"   📊 {stat.status}:")
            print(f"      Total: {stat.total}")
            print(f"      Com texto_bruto: {stat.com_texto_bruto}")
            print(f"      Com texto_processado: {stat.com_texto_processado}")
            print(f"      Tamanho médio texto_bruto: {stat.avg_tamanho_bruto:.0f} chars")
            print(f"      Tamanho médio texto_processado: {stat.avg_tamanho_processado:.0f} chars")
        
        # Contagem de clusters
        query = text("""
            SELECT 
                COUNT(*) as total_clusters,
                COUNT(CASE WHEN resumo_cluster IS NOT NULL THEN 1 END) as com_resumo,
                COUNT(CASE WHEN prioridade = 'IRRELEVANTE' THEN 1 END) as irrelevantes
            FROM clusters_eventos
            WHERE status = 'ativo'
        """)
        
        cluster_stats = db.execute(query).fetchone()
        print(f"\n📊 Clusters:")
        print(f"   Total ativos: {cluster_stats.total_clusters}")
        print(f"   Com resumo: {cluster_stats.com_resumo}")
        print(f"   Irrelevantes: {cluster_stats.irrelevantes}")
        
        db.close()
        
    except Exception as e:
        print(f"❌ ERRO ao verificar estatísticas: {e}")

def testar_api_artigo(artigo_id: int):
    """Testa a API de artigo individual"""
    print_header(f"🌐 TESTANDO API /api/artigo/{artigo_id}")
    
    try:
        import requests
        
        url = f"http://localhost:8000/api/artigo/{artigo_id}"
        print(f"🌐 Fazendo requisição para: {url}")
        
        response = requests.get(url, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        print(f"📊 Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Resposta da API:")
            print(f"   ID: {data.get('id')}")
            print(f"   Título: {data.get('titulo_extraido')}")
            print(f"   Jornal: {data.get('jornal')}")
            print(f"   Tag: {data.get('tag')}")
            print(f"   Prioridade: {data.get('prioridade')}")
            
            # Verifica campos de texto
            texto_bruto = data.get('texto_bruto')
            texto_processado = data.get('texto_processado')
            
            if texto_bruto:
                print(f"   📖 texto_bruto: {len(texto_bruto)} chars")
                print(f"      Início: {texto_bruto[:100]}...")
            else:
                print(f"   ❌ texto_bruto: NÃO RETORNADO")
            
            if texto_processado:
                print(f"   📝 texto_processado: {len(texto_processado)} chars")
                print(f"      Início: {texto_processado[:100]}...")
            else:
                print(f"   ❌ texto_processado: NÃO RETORNADO")
                
        else:
            print(f"❌ ERRO na API: {response.status_code}")
            print(f"   Resposta: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ ERRO: Não foi possível conectar com a API (backend não está rodando?)")
    except Exception as e:
        print(f"❌ ERRO ao testar API: {e}")

def main():
    """Função principal do diagnóstico"""
    print_header("🔬 DIAGNÓSTICO COMPLETO DO FLUXO DE NOTÍCIAS", "=", 80)
    print(f"📅 Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Verificar conexão com banco
    if not verificar_conexao_banco():
        print("❌ Falha na conexão com banco. Abortando diagnóstico.")
        return
    
    # 2. Verificar estrutura das tabelas
    verificar_estrutura_tabelas()
    
    # 3. Verificar estatísticas gerais
    verificar_estatisticas_gerais()
    
    # 4. Encontrar notícia para análise
    cluster = encontrar_noticia_com_multiplas_fontes()
    if not cluster:
        print("❌ Não foi possível encontrar notícia para análise.")
        return
    
    # 5. Analisar cluster completo
    if not analisar_cluster_completo(cluster.cluster_id):
        print("❌ Falha na análise do cluster.")
        return
    
    # 6. Testar API (se backend estiver rodando)
    print_header("🌐 TESTE DA API")
    print("⚠️ Para testar a API, certifique-se de que o backend está rodando:")
    print("   python start_dev.py")
    
    # Pega o primeiro artigo do cluster para testar API
    try:
        db = SessionLocal()
        artigos = get_artigos_by_cluster(db, cluster.cluster_id)
        if artigos:
            primeiro_artigo = artigos[0]
            print(f"\n🎯 Testando API com artigo ID: {primeiro_artigo.id}")
            testar_api_artigo(primeiro_artigo.id)
        db.close()
    except Exception as e:
        print(f"⚠️ Não foi possível testar API: {e}")
    
    # 7. RESUMO FINAL
    print_header("📋 RESUMO DO DIAGNÓSTICO", "=", 80)
    print("✅ DIAGNÓSTICO CONCLUÍDO!")
    print("\n🔍 PRÓXIMOS PASSOS:")
    print("1. Analise os dados acima para identificar problemas")
    print("2. Verifique se texto_bruto contém texto original dos PDFs")
    print("3. Verifique se texto_processado contém resumos")
    print("4. Teste a API se o backend estiver rodando")
    print("5. Identifique onde está a desconexão dos dados")
    
    print("\n🚨 PROBLEMAS MAIS PROVÁVEIS:")
    print("- texto_bruto sendo sobrescrito em algum lugar")
    print("- API retornando campo errado")
    print("- Frontend lendo campo errado")
    print("- LLM sendo chamado na ETAPA 1 (não deveria)")

if __name__ == "__main__":
    main()
