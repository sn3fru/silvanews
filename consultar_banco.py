#!/usr/bin/env python3
"""
Script para consultar o banco de dados e mostrar registros de cada tabela.
Permite alterar as consultas facilmente para debug.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import text, func
from sqlalchemy.orm import sessionmaker
import json

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Carrega variáveis de ambiente
from dotenv import load_dotenv
env_file = backend_dir / ".env"
load_dotenv(env_file)

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento, LogProcessamento

def conectar_banco():
    """Conecta ao banco de dados."""
    try:
        # Usa o SessionLocal já configurado no database.py
        session = SessionLocal()
        print("✅ Conectado ao banco de dados com sucesso!")
        return session
    except Exception as e:
        print(f"❌ Erro ao conectar ao banco: {e}")
        return None

def consultar_artigos_brutos(session, limit=5):
    """Consulta artigos brutos."""
    print("\n" + "="*60)
    print("📰 ARTIGOS BRUTOS")
    print("="*60)
    
    try:
        # ALTERE ESTA CONSULTA CONFORME NECESSÁRIO
        artigos = session.query(ArtigoBruto).limit(limit).all()
        
        if not artigos:
            print("❌ Nenhum artigo bruto encontrado")
            return
        
        print(f"📊 Total de artigos brutos: {session.query(ArtigoBruto).count()}")
        print(f"🔍 Mostrando {len(artigos)} registros:\n")
        
        for i, artigo in enumerate(artigos, 1):
            print(f"📄 Artigo {i}:")
            print(f"   ID: {artigo.id}")
            print(f"   Título: {artigo.titulo_extraido[:100] if artigo.titulo_extraido else 'Sem título'}{'...' if artigo.titulo_extraido and len(artigo.titulo_extraido) > 100 else ''}")
            print(f"   Jornal: {artigo.jornal}")
            print(f"   Status: {artigo.status}")
            print(f"   Tag: {artigo.tag}")
            print(f"   Prioridade: {artigo.prioridade}")
            print(f"   Cluster ID: {artigo.cluster_id}")
            print(f"   Criado em: {artigo.created_at}")
            print(f"   Processado em: {artigo.processed_at}")
            print("-" * 40)
            
    except Exception as e:
        print(f"❌ Erro ao consultar artigos brutos: {e}")

def consultar_clusters(session, limit=5):
    """Consulta clusters de eventos."""
    print("\n" + "="*60)
    print("🎯 CLUSTERS DE EVENTOS")
    print("="*60)
    
    try:
        # ALTERE ESTA CONSULTA CONFORME NECESSÁRIO
        clusters = session.query(ClusterEvento).limit(limit).all()
        
        if not clusters:
            print("❌ Nenhum cluster encontrado")
            return
        
        print(f"📊 Total de clusters: {session.query(ClusterEvento).count()}")
        print(f"🔍 Mostrando {len(clusters)} registros:\n")
        
        for i, cluster in enumerate(clusters, 1):
            print(f"🎯 Cluster {i}:")
            print(f"   ID: {cluster.id}")
            print(f"   Título: {cluster.titulo_cluster[:100]}{'...' if len(cluster.titulo_cluster) > 100 else ''}")
            print(f"   Tag: {cluster.tag}")
            print(f"   Prioridade: {cluster.prioridade}")
            print(f"   Resumo: {cluster.resumo_cluster[:150] if cluster.resumo_cluster else 'Sem resumo'}{'...' if cluster.resumo_cluster and len(cluster.resumo_cluster) > 150 else ''}")
            print(f"   Criado em: {cluster.created_at}")
            print(f"   Atualizado em: {cluster.updated_at}")
            print("-" * 40)
            
    except Exception as e:
        print(f"❌ Erro ao consultar clusters: {e}")

def consultar_logs(session, limit=5):
    """Consulta logs."""
    print("\n" + "="*60)
    print("📋 LOGS")
    print("="*60)
    
    try:
        # ALTERE ESTA CONSULTA CONFORME NECESSÁRIO
        logs = session.query(LogProcessamento).order_by(LogProcessamento.timestamp.desc()).limit(limit).all()
        
        if not logs:
            print("❌ Nenhum log encontrado")
            return
        
        print(f"📊 Total de logs: {session.query(LogProcessamento).count()}")
        print(f"🔍 Mostrando {len(logs)} registros mais recentes:\n")
        
        for i, log in enumerate(logs, 1):
            print(f"📋 Log {i}:")
            print(f"   ID: {log.id}")
            print(f"   Nível: {log.nivel}")
            print(f"   Componente: {log.componente}")
            print(f"   Mensagem: {log.mensagem[:100]}{'...' if len(log.mensagem) > 100 else ''}")
            print(f"   Timestamp: {log.timestamp}")
            print("-" * 40)
            
    except Exception as e:
        print(f"❌ Erro ao consultar logs: {e}")

def consulta_customizada(session, query_sql):
    """Executa uma consulta SQL customizada."""
    print("\n" + "="*60)
    print("🔧 CONSULTA CUSTOMIZADA")
    print("="*60)
    
    try:
        result = session.execute(text(query_sql))
        rows = result.fetchall()
        
        if not rows:
            print("❌ Nenhum resultado encontrado")
            return
        
        print(f"📊 Total de resultados: {len(rows)}")
        print(f"🔍 Colunas: {result.keys()}")
        print("\nResultados:")
        
        for i, row in enumerate(rows, 1):
            print(f"📄 Registro {i}:")
            for key, value in row._mapping.items():
                if isinstance(value, str) and len(value) > 100:
                    print(f"   {key}: {value[:100]}...")
                else:
                    print(f"   {key}: {value}")
            print("-" * 40)
            
    except Exception as e:
        print(f"❌ Erro na consulta customizada: {e}")

def mostrar_estatisticas(session):
    """Mostra estatísticas gerais do banco."""
    print("\n" + "="*60)
    print("📊 ESTATÍSTICAS GERAIS")
    print("="*60)
    
    try:
        # Contagem de registros
        total_artigos = session.query(ArtigoBruto).count()
        total_clusters = session.query(ClusterEvento).count()
        total_logs = session.query(LogProcessamento).count()
        
        # Artigos por status
        status_counts = session.query(ArtigoBruto.status, func.count(ArtigoBruto.id)).group_by(ArtigoBruto.status).all()
        
        # Clusters por prioridade
        prioridade_counts = session.query(ClusterEvento.prioridade, func.count(ClusterEvento.id)).group_by(ClusterEvento.prioridade).all()
        
        # Artigos por data (últimos 7 dias)
        from datetime import timedelta
        data_limite = datetime.utcnow() - timedelta(days=7)
        artigos_por_data = session.query(
            func.date(ArtigoBruto.created_at).label('data'),
            func.count(ArtigoBruto.id).label('total')
        ).filter(
            ArtigoBruto.created_at >= data_limite
        ).group_by(
            func.date(ArtigoBruto.created_at)
        ).order_by(
            func.date(ArtigoBruto.created_at).desc()
        ).all()
        
        # Artigos por prioridade
        artigos_por_prioridade = session.query(
            ArtigoBruto.prioridade,
            func.count(ArtigoBruto.id).label('total')
        ).group_by(ArtigoBruto.prioridade).all()
        
        print(f"📰 Total de artigos brutos: {total_artigos}")
        print(f"🎯 Total de clusters: {total_clusters}")
        print(f"📋 Total de logs: {total_logs}")
        
        print("\n📊 Artigos por status:")
        for status, count in status_counts:
            print(f"   {status}: {count}")
        
        print("\n📊 Clusters por prioridade:")
        for prioridade, count in prioridade_counts:
            print(f"   {prioridade}: {count}")
        
        print("\n📊 Artigos por data (últimos 7 dias):")
        for data, count in artigos_por_data:
            print(f"   {data}: {count} artigos")
        
        print("\n📊 Artigos por prioridade:")
        for prioridade, count in artigos_por_prioridade:
            print(f"   {prioridade}: {count} artigos")
            
    except Exception as e:
        print(f"❌ Erro ao calcular estatísticas: {e}")

def main():
    """Função principal."""
    print("🔍 CONSULTOR DE BANCO DE DADOS - BTG AlphaFeed")
    print("="*60)
    
    # Conecta ao banco
    session = conectar_banco()
    if not session:
        return
    
    try:
        # Mostra estatísticas gerais
        mostrar_estatisticas(session)
        
        # Consulta cada tabela
        consultar_artigos_brutos(session, limit=3)
        consultar_clusters(session, limit=3)
        consultar_logs(session, limit=3)
        
        # Exemplo de consulta customizada
        print("\n" + "="*60)
        print("💡 EXEMPLOS DE CONSULTAS CUSTOMIZADAS")
        print("="*60)
        print("Para executar consultas customizadas, modifique a função consulta_customizada()")
        print("ou adicione suas consultas no código.")
        print("\nExemplos de consultas úteis:")
        print("1. SELECT COUNT(*) as total, status FROM artigos_brutos GROUP BY status;")
        print("2. SELECT COUNT(*) as total, prioridade FROM clusters_eventos GROUP BY prioridade;")
        print("3. SELECT * FROM artigos_brutos WHERE cluster_id IS NULL LIMIT 5;")
        print("4. SELECT * FROM clusters_eventos WHERE resumo_cluster IS NULL LIMIT 5;")
        
        # Exemplo: artigos sem cluster
        print("\n🔍 Artigos sem cluster (pendentes de agrupamento):")
        consulta_customizada(session, "SELECT COUNT(*) as total FROM artigos_brutos WHERE cluster_id IS NULL")
        
        # Exemplo: clusters sem resumo
        print("\n🔍 Clusters sem resumo:")
        consulta_customizada(session, "SELECT COUNT(*) as total FROM clusters_eventos WHERE resumo_cluster IS NULL")
        
        # Exemplo: artigos por data (últimos 30 dias)
        print("\n🔍 Artigos por data (últimos 30 dias):")
        consulta_customizada(session, """
            SELECT 
                DATE(created_at) as data,
                COUNT(*) as total_artigos
            FROM artigos_brutos 
            WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY data DESC
        """)
        
        # Exemplo: artigos por prioridade
        print("\n🔍 Artigos por prioridade:")
        consulta_customizada(session, """
            SELECT 
                prioridade,
                COUNT(*) as total_artigos
            FROM artigos_brutos 
            GROUP BY prioridade
            ORDER BY total_artigos DESC
        """)
        
    except Exception as e:
        print(f"❌ Erro geral: {e}")
    
    finally:
        session.close()
        print("\n✅ Sessão do banco fechada")

if __name__ == "__main__":
    main() 