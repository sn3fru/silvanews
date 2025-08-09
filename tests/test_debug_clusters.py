#!/usr/bin/env python3
"""
Script de debug para verificar o estado dos clusters e artigos no banco.
"""

import sys
from pathlib import Path
from datetime import datetime, date
from sqlalchemy import func

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento

def debug_banco():
    """Debug do estado do banco de dados"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("DEBUG DO BANCO DE DADOS")
        print("=" * 60)
        
        # Estatísticas gerais
        total_artigos = db.query(ArtigoBruto).count()
        artigos_pendentes = db.query(ArtigoBruto).filter(ArtigoBruto.status == "pendente").count()
        artigos_processados = db.query(ArtigoBruto).filter(ArtigoBruto.status == "processado").count()
        artigos_erro = db.query(ArtigoBruto).filter(ArtigoBruto.status == "erro").count()
        
        print(f"📊 ESTATÍSTICAS GERAIS:")
        print(f"   Total de artigos: {total_artigos}")
        print(f"   Artigos pendentes: {artigos_pendentes}")
        print(f"   Artigos processados: {artigos_processados}")
        print(f"   Artigos com erro: {artigos_erro}")
        
        # Clusters
        total_clusters = db.query(ClusterEvento).count()
        clusters_ativos = db.query(ClusterEvento).filter(ClusterEvento.status == "ativo").count()
        
        print(f"\n🔗 CLUSTERS:")
        print(f"   Total de clusters: {total_clusters}")
        print(f"   Clusters ativos: {clusters_ativos}")
        
        # Artigos com cluster_id
        artigos_com_cluster = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id.isnot(None)).count()
        print(f"   Artigos associados a clusters: {artigos_com_cluster}")
        
        # Verificar artigos de hoje
        hoje = date.today()
        artigos_hoje = db.query(ArtigoBruto).filter(
            func.date(ArtigoBruto.created_at) == hoje
        ).count()
        
        artigos_processados_hoje = db.query(ArtigoBruto).filter(
            func.date(ArtigoBruto.created_at) == hoje,
            ArtigoBruto.status == "processado"
        ).count()
        
        print(f"\n📅 ARTIGOS DE HOJE ({hoje}):")
        print(f"   Total de artigos: {artigos_hoje}")
        print(f"   Artigos processados: {artigos_processados_hoje}")
        
        # Clusters de hoje
        clusters_hoje = db.query(ClusterEvento).join(
            ArtigoBruto, ClusterEvento.id == ArtigoBruto.cluster_id
        ).filter(
            func.date(ArtigoBruto.created_at) == hoje,
            ClusterEvento.status == 'ativo'
        ).distinct().count()
        
        print(f"   Clusters ativos: {clusters_hoje}")
        
        # Verificar alguns artigos processados
        print(f"\n📰 AMOSTRA DE ARTIGOS PROCESSADOS:")
        artigos_amostra = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "processado"
        ).limit(5).all()
        
        for i, artigo in enumerate(artigos_amostra, 1):
            print(f"   {i}. ID: {artigo.id}, Título: {artigo.titulo_extraido[:50]}...")
            print(f"      Status: {artigo.status}, Cluster: {artigo.cluster_id}")
            print(f"      Created: {artigo.created_at}, Processed: {artigo.processed_at}")
        
        # Verificar clusters
        print(f"\n🔗 AMOSTRA DE CLUSTERS:")
        clusters_amostra = db.query(ClusterEvento).limit(5).all()
        
        for i, cluster in enumerate(clusters_amostra, 1):
            print(f"   {i}. ID: {cluster.id}, Título: {cluster.titulo_cluster[:50]}...")
            print(f"      Status: {cluster.status}, Prioridade: {cluster.prioridade}")
            print(f"      Created: {cluster.created_at}")
            
            # Contar artigos do cluster
            artigos_cluster = db.query(ArtigoBruto).filter(
                ArtigoBruto.cluster_id == cluster.id
            ).count()
            print(f"      Artigos: {artigos_cluster}")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    debug_banco() 