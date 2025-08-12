#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Teste para verificar o funcionamento do agrupamento incremental.
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, init_database
from crud import (
    get_artigos_processados_hoje, 
    get_clusters_existentes_hoje,
    get_cluster_com_artigos,
    create_log
)
from prompts import PROMPT_AGRUPAMENTO_INCREMENTAL_V2
import json


def test_incremental_clustering():
    """Testa as funções de agrupamento incremental."""
    
    print("🧪 Testando Agrupamento Incremental...")
    
    # Inicializa banco
    init_database()
    db = SessionLocal()
    
    try:
        # Testa busca de artigos processados hoje
        print("\n1. Buscando artigos processados hoje...")
        artigos_novos = get_artigos_processados_hoje(db)
        print(f"   ✅ Encontrados {len(artigos_novos)} artigos novos")
        
        # Testa busca de clusters existentes hoje
        print("\n2. Buscando clusters existentes hoje...")
        clusters_existentes = get_clusters_existentes_hoje(db)
        print(f"   ✅ Encontrados {len(clusters_existentes)} clusters existentes")
        
        # Testa obtenção de cluster com artigos
        if clusters_existentes:
            print("\n3. Testando obtenção de cluster com artigos...")
            cluster_data = get_cluster_com_artigos(db, clusters_existentes[0].id)
            if cluster_data:
                print(f"   ✅ Cluster {cluster_data['id']} obtido com {len(cluster_data['artigos'])} artigos")
            else:
                print("   ❌ Erro ao obter dados do cluster")
        
        # Testa prompt de agrupamento incremental
        print("\n4. Testando prompt de agrupamento incremental...")
        if artigos_novos and clusters_existentes:
            # Prepara dados de exemplo
            novas_noticias = []
            for i, artigo in enumerate(artigos_novos[:3]):  # Limita a 3 para teste
                noticia_data = {
                    "id": i,
                    "titulo": artigo.titulo_extraido or "Sem título",
                    "jornal": artigo.jornal or "Fonte desconhecida",
                    "trecho": (artigo.texto_processado[:300] + "...") if len(artigo.texto_processado or "") > 300 else (artigo.texto_processado or "")
                }
                novas_noticias.append(noticia_data)
            
            clusters_existentes_data = []
            for cluster in clusters_existentes[:2]:  # Limita a 2 para teste
                cluster_data = get_cluster_com_artigos(db, cluster.id)
                if cluster_data:
                    clusters_existentes_data.append({
                        "cluster_id": cluster_data["id"],
                        "tema_principal": cluster_data["titulo_cluster"],
                        "titulos_internos": [a["titulo"] for a in cluster_data.get("artigos", [])][:30]
                    })
            
            # Monta o prompt
            prompt_completo = PROMPT_AGRUPAMENTO_INCREMENTAL_V2.format(
                NOVAS_NOTICIAS=json.dumps(novas_noticias, indent=2, ensure_ascii=False),
                CLUSTERS_EXISTENTES=json.dumps(clusters_existentes_data, indent=2, ensure_ascii=False)
            )
            
            print(f"   ✅ Prompt montado com {len(novas_noticias)} notícias novas e {len(clusters_existentes_data)} clusters existentes")
            print(f"   📝 Tamanho do prompt: {len(prompt_completo)} caracteres")
        else:
            print("   ⚠️ Dados insuficientes para testar prompt completo")
        
        # Log de teste
        create_log(db, "INFO", "test", "Teste de agrupamento incremental executado com sucesso")
        
        print("\n✅ Teste de agrupamento incremental concluído!")
        
    except Exception as e:
        print(f"\n❌ Erro no teste: {e}")
        create_log(db, "ERROR", "test", f"Erro no teste de agrupamento incremental: {e}")
    
    finally:
        db.close()


if __name__ == "__main__":
    test_incremental_clustering() 