#!/usr/bin/env python3
"""
Script para testar o fluxo completo do BTG AlphaFeed.
Simula o processo completo: carregamento -> processamento -> clusterização -> resumos.
"""

import sys
import time
from pathlib import Path

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.database import SessionLocal
from backend.crud import (
    get_artigos_pendentes, get_database_stats, get_active_clusters_today,
    get_clusters_for_feed, get_cluster_by_id, get_artigos_by_cluster
)
from backend.processing import processar_artigo_pipeline, gerar_resumo_cluster
from google import genai
import os
from dotenv import load_dotenv

def test_fluxo_completo():
    """Testa o fluxo completo do sistema."""
    print("Testando fluxo completo do BTG AlphaFeed...")
    print("=" * 60)
    
    # Carrega configurações
    load_dotenv(backend_dir / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERRO: GEMINI_API_KEY não configurada")
        return False
    
    client = genai.Client(api_key=api_key)
    print("SUCESSO: Gemini configurado")
    
    db = SessionLocal()
    try:
        # ETAPA 1: Verificar estado inicial
        print("\nETAPA 1: Estado inicial do banco")
        stats_inicial = get_database_stats(db)
        print(f"   Total de artigos: {stats_inicial['total_artigos']}")
        print(f"   Artigos processados: {stats_inicial['artigos_processados']}")
        print(f"   Artigos com erro: {stats_inicial['artigos_erro']}")
        print(f"   Clusters existentes: {stats_inicial['clusters_existentes']}")
        
        # Busca artigos pendentes
        artigos_pendentes = get_artigos_pendentes(db, 5)
        print(f"   Artigos pendentes: {len(artigos_pendentes)}")
        
        if not artigos_pendentes:
            print("ERRO: Nenhum artigo pendente encontrado. Execute primeiro o load_news.py")
            return False
        
        # ETAPA 2: Processar artigos pendentes
        print(f"\nETAPA 2: Processando {len(artigos_pendentes)} artigos pendentes...")
        
        sucessos = 0
        erros = 0
        clusters_atualizados = set()
        
        for i, artigo in enumerate(artigos_pendentes, 1):
            print(f"  Processando artigo {i}/{len(artigos_pendentes)} (ID: {artigo.id})...")
            
            if processar_artigo_pipeline(db, artigo.id, client):
                sucessos += 1
                
                # Verifica se foi associado a um cluster
                db.refresh(artigo)
                if artigo.cluster_id:
                    clusters_atualizados.add(artigo.cluster_id)
                    print(f"    SUCESSO: Artigo associado ao cluster {artigo.cluster_id}")
                else:
                    print(f"    INFO: Artigo não foi associado a nenhum cluster")
            else:
                erros += 1
                print(f"    ERRO: Falha no processamento")
            
            time.sleep(2)  # Pausa entre processamentos
        
        print(f"\nSUCESSO: Processamento de artigos finalizado:")
        print(f"   Artigos processados: {len(artigos_pendentes)}")
        print(f"   Sucessos: {sucessos}")
        print(f"   Erros: {erros}")
        print(f"   Clusters atualizados: {len(clusters_atualizados)}")
        
        # ETAPA 3: Gerar resumos para clusters P1 e P2
        if clusters_atualizados:
            print(f"\nETAPA 3: Gerando resumos para clusters atualizados...")
            
            resumos_gerados = 0
            
            for cluster_id in clusters_atualizados:
                cluster = get_cluster_by_id(db, cluster_id)
                if not cluster:
                    continue
                
                # Verifica prioridade do cluster
                prioridade = cluster.prioridade
                if prioridade in ['P1_CRITICO', 'P2_ESTRATEGICO']:
                    print(f"  Gerando resumo para cluster {cluster_id} (Prioridade: {prioridade})...")
                    
                    if gerar_resumo_cluster(db, cluster_id, client):
                        resumos_gerados += 1
                        print(f"    SUCESSO: Resumo gerado com sucesso")
                    else:
                        print(f"    ERRO: Falha ao gerar resumo")
                else:
                    print(f"  INFO: Cluster {cluster_id} (Prioridade: {prioridade}) não requer resumo. Pulando.")
            
            print(f"\nResumos gerados: {resumos_gerados}")
        
        # ETAPA 4: Verificar estado final
        print(f"\nETAPA 4: Estado final do banco")
        stats_final = get_database_stats(db)
        print(f"   Total de artigos: {stats_final['total_artigos']}")
        print(f"   Artigos processados: {stats_final['artigos_processados']}")
        print(f"   Artigos com erro: {stats_final['artigos_erro']}")
        print(f"   Clusters existentes: {stats_final['clusters_existentes']}")
        
        # ETAPA 5: Verificar clusters para o feed
        print(f"\nETAPA 5: Verificando clusters para o feed...")
        clusters_feed = get_clusters_for_feed(db)
        print(f"   Clusters disponíveis no feed: {len(clusters_feed)}")
        
        for i, cluster_data in enumerate(clusters_feed[:3], 1):
            print(f"   {i}. ID: {cluster_data['id']}, Título: {cluster_data['titulo_final']}")
            print(f"      Prioridade: {cluster_data['prioridade']}, Fontes: {len(cluster_data['fontes'])}")
            print(f"      Resumo: {cluster_data['resumo_final'][:100]}...")
        
        # ETAPA 6: Testar acesso a artigos originais
        if clusters_feed:
            print(f"\nETAPA 6: Testando acesso a artigos originais...")
            cluster_teste = clusters_feed[0]
            cluster_id = cluster_teste['id']
            
            artigos_cluster = get_artigos_by_cluster(db, cluster_id)
            print(f"   Cluster {cluster_id} tem {len(artigos_cluster)} artigos:")
            
            for i, artigo in enumerate(artigos_cluster[:3], 1):
                print(f"      {i}. ID: {artigo.id}, Título: {artigo.titulo_extraido}")
                print(f"         Jornal: {artigo.jornal}, URL: {artigo.url_original}")
                print(f"         Texto: {artigo.texto_processado[:100]}...")
        
        print(f"\nSUCESSO: Teste do fluxo completo finalizado!")
        print(f"INFO: Agora você pode acessar o frontend para ver os resultados")
        
        return True
        
    except Exception as e:
        print(f"ERRO: Erro no teste do fluxo completo: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    sucesso = test_fluxo_completo()
    if not sucesso:
        sys.exit(1) 