#!/usr/bin/env python3
"""
Script de teste para verificar se o agrupamento está funcionando.
"""

import sys
from pathlib import Path
from datetime import datetime, date
from sqlalchemy import func

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
from process_articles import agrupar_noticias_com_prompt
import os
from dotenv import load_dotenv
from google import genai

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
load_dotenv(env_file)

# Configuração do Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERRO: GEMINI_API_KEY não configurada")
    sys.exit(1)

client = genai.Client(api_key=api_key)

def test_agrupamento():
    """Testa o agrupamento de notícias"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("TESTE DE AGRUPAMENTO")
        print("=" * 60)
        
        # Verifica artigos processados hoje
        hoje = date.today()
        artigos_hoje = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == "processado",
            func.date(ArtigoBruto.created_at) == hoje
        ).all()
        
        print(f"📰 Artigos processados hoje: {len(artigos_hoje)}")
        
        if not artigos_hoje:
            print("❌ Nenhum artigo processado hoje encontrado")
            return False
        
        # Mostra alguns artigos
        print(f"\n📋 AMOSTRA DE ARTIGOS:")
        for i, artigo in enumerate(artigos_hoje[:3], 1):
            print(f"   {i}. ID: {artigo.id}")
            print(f"      Título: {artigo.titulo_extraido}")
            print(f"      Jornal: {artigo.jornal}")
            print(f"      Tag: {artigo.tag}")
            print(f"      Prioridade: {artigo.prioridade}")
            print()
        
        # Testa o agrupamento
        print(f"🔄 TESTANDO AGRUPAMENTO...")
        sucesso = agrupar_noticias_com_prompt(db, client)
        
        if sucesso:
            print("✅ Agrupamento realizado com sucesso!")
            
            # Verifica clusters criados
            clusters_hoje = db.query(ClusterEvento).filter(
                ClusterEvento.created_at >= hoje
            ).all()
            
            print(f"🔗 Clusters criados: {len(clusters_hoje)}")
            
            for i, cluster in enumerate(clusters_hoje, 1):
                print(f"   {i}. ID: {cluster.id}")
                print(f"      Título: {cluster.titulo_cluster}")
                print(f"      Tag: {cluster.tag}")
                print(f"      Prioridade: {cluster.prioridade}")
                
                # Conta artigos do cluster
                artigos_cluster = db.query(ArtigoBruto).filter(
                    ArtigoBruto.cluster_id == cluster.id
                ).count()
                print(f"      Artigos: {artigos_cluster}")
                print()
            
            return True
        else:
            print("❌ Falha no agrupamento")
            return False
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    test_agrupamento() 