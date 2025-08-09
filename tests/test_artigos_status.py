#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Teste para verificar o status dos artigos no banco de dados.
Versão otimizada - não requer servidor.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, date

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, init_database, ArtigoBruto, ClusterEvento
from sqlalchemy import func, and_


def test_artigos_status():
    """Testa o status dos artigos no banco de dados."""
    
    print("🔍 Verificando Status dos Artigos (Versão Otimizada)...")
    
    # Inicializa banco
    init_database()
    db = SessionLocal()
    
    try:
        hoje = date.today()
        
        # Conta artigos por status
        print("\n1. Contagem de artigos por status:")
        status_counts = db.query(
            ArtigoBruto.status, 
            func.count(ArtigoBruto.id).label('count')
        ).group_by(ArtigoBruto.status).all()
        
        for status, count in status_counts:
            print(f"   📊 {status}: {count} artigos")
        
        # Conta artigos criados hoje
        print(f"\n2. Artigos criados hoje ({hoje}):")
        artigos_hoje = db.query(ArtigoBruto).filter(
            func.date(ArtigoBruto.created_at) == hoje
        ).all()
        
        print(f"   📅 Total de artigos criados hoje: {len(artigos_hoje)}")
        
        # Conta artigos processados hoje
        print(f"\n3. Artigos processados hoje ({hoje}):")
        artigos_processados_hoje = db.query(ArtigoBruto).filter(
            func.date(ArtigoBruto.processed_at) == hoje
        ).all()
        
        print(f"   ⚙️ Total de artigos processados hoje: {len(artigos_processados_hoje)}")
        
        # Conta artigos pendentes
        print(f"\n4. Artigos pendentes:")
        artigos_pendentes = db.query(ArtigoBruto).filter(
            ArtigoBruto.status == 'pendente'
        ).all()
        
        print(f"   ⏳ Total de artigos pendentes: {len(artigos_pendentes)}")
        
        # Conta artigos processados mas sem cluster
        print(f"\n5. Artigos processados mas sem cluster:")
        artigos_sem_cluster = db.query(ArtigoBruto).filter(
            and_(
                ArtigoBruto.status == 'processado',
                ArtigoBruto.cluster_id.is_(None)
            )
        ).all()
        
        print(f"   🔗 Artigos processados sem cluster: {len(artigos_sem_cluster)}")
        
        # Conta clusters criados hoje
        print(f"\n6. Clusters criados hoje ({hoje}):")
        clusters_hoje = db.query(ClusterEvento).filter(
            func.date(ClusterEvento.created_at) == hoje
        ).all()
        
        print(f"   📦 Total de clusters criados hoje: {len(clusters_hoje)}")
        
        # Mostra alguns exemplos de artigos pendentes
        if artigos_pendentes:
            print(f"\n7. Exemplos de artigos pendentes:")
            for i, artigo in enumerate(artigos_pendentes[:3], 1):
                print(f"   {i}. ID: {artigo.id}, Criado: {artigo.created_at}")
                if artigo.titulo_extraido:
                    print(f"      Título: {artigo.titulo_extraido[:50]}...")
                else:
                    print(f"      Texto: {artigo.texto_bruto[:50]}...")
        
        # Mostra alguns exemplos de artigos processados sem cluster
        if artigos_sem_cluster:
            print(f"\n8. Exemplos de artigos processados sem cluster:")
            for i, artigo in enumerate(artigos_sem_cluster[:3], 1):
                print(f"   {i}. ID: {artigo.id}, Processado: {artigo.processed_at}")
                if artigo.titulo_extraido:
                    print(f"      Título: {artigo.titulo_extraido[:50]}...")
                else:
                    print(f"      Texto: {artigo.texto_bruto[:50]}...")
        
        # Análise para agrupamento incremental
        print(f"\n9. Análise para Agrupamento Incremental:")
        artigos_para_incremental = db.query(ArtigoBruto).filter(
            and_(
                func.date(ArtigoBruto.processed_at) == hoje,
                ArtigoBruto.cluster_id.is_(None)
            )
        ).all()
        
        print(f"   🎯 Artigos processados hoje sem cluster: {len(artigos_para_incremental)}")
        
        if artigos_para_incremental:
            print(f"   📝 Exemplos de títulos para agrupamento:")
            for i, artigo in enumerate(artigos_para_incremental[:5], 1):
                titulo = artigo.titulo_extraido or artigo.texto_bruto[:50]
                print(f"      {i}. ID {artigo.id}: {titulo}...")
        
        print("\n✅ Verificação de status concluída!")
        
        # Recomendações
        print(f"\n💡 Recomendações:")
        if len(artigos_pendentes) > 0:
            print(f"   • Processe os {len(artigos_pendentes)} artigos pendentes")
        if len(artigos_para_incremental) > 0:
            print(f"   • Execute agrupamento incremental para {len(artigos_para_incremental)} artigos")
        if len(artigos_para_incremental) == 0 and len(artigos_pendentes) == 0:
            print(f"   • Todos os artigos estão processados e agrupados!")
        
    except Exception as e:
        print(f"\n❌ Erro na verificação: {e}")
    
    finally:
        db.close()


if __name__ == "__main__":
    test_artigos_status() 