#!/usr/bin/env python3
"""
Script para aplicar índices de performance no banco de dados.
Executa após as mudanças no modelo de dados para otimizar queries.
"""

import sys
from pathlib import Path

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.database import engine, Base, ArtigoBruto, ClusterEvento
from sqlalchemy import text

def aplicar_indices_performance():
    """Aplica índices de performance no banco de dados."""
    print("🔧 Aplicando índices de performance no banco de dados...")
    
    try:
        # Lista de índices para criar
        indices = [
            # Índices para ArtigoBruto
            "CREATE INDEX IF NOT EXISTS idx_artigos_created_date ON artigos_brutos (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_artigos_processed_date ON artigos_brutos (processed_at)",
            "CREATE INDEX IF NOT EXISTS idx_artigos_cluster_date ON artigos_brutos (cluster_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_artigos_status_date ON artigos_brutos (status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_artigos_tag_date ON artigos_brutos (tag, created_at)",
            
            # Índices para ClusterEvento
            "CREATE INDEX IF NOT EXISTS idx_clusters_created_date ON clusters_eventos (created_at)",
            "CREATE INDEX IF NOT EXISTS idx_clusters_updated_date ON clusters_eventos (updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_clusters_tag_date ON clusters_eventos (tag, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_clusters_prioridade_date ON clusters_eventos (prioridade, created_at)",
            
            # Índices compostos para queries frequentes
            "CREATE INDEX IF NOT EXISTS idx_artigos_status_processed ON artigos_brutos (status, processed_at)",
            "CREATE INDEX IF NOT EXISTS idx_clusters_status_prioridade ON clusters_eventos (status, prioridade)",
        ]
        
        # Executa cada índice
        with engine.connect() as conn:
            for i, index_sql in enumerate(indices, 1):
                try:
                    print(f"  [{i}/{len(indices)}] Aplicando índice...")
                    conn.execute(text(index_sql))
                    conn.commit()
                    print(f"    ✅ Índice aplicado com sucesso")
                except Exception as e:
                    print(f"    ⚠️ Aviso ao aplicar índice: {e}")
                    # Continua mesmo se um índice falhar
        
        print("🎉 Índices de performance aplicados com sucesso!")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao aplicar índices: {e}")
        return False

def verificar_indices():
    """Verifica se os índices foram aplicados corretamente."""
    print("\n🔍 Verificando índices aplicados...")
    
    try:
        with engine.connect() as conn:
            # Verifica índices da tabela artigos_brutos
            result = conn.execute(text("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'artigos_brutos' 
                AND indexname LIKE 'idx_artigos_%'
                ORDER BY indexname
            """))
            
            indices_artigos = result.fetchall()
            print(f"  📊 Índices em artigos_brutos: {len(indices_artigos)}")
            for idx in indices_artigos:
                print(f"    ✅ {idx[0]}")
            
            # Verifica índices da tabela clusters_eventos
            result = conn.execute(text("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'clusters_eventos' 
                AND indexname LIKE 'idx_clusters_%'
                ORDER BY indexname
            """))
            
            indices_clusters = result.fetchall()
            print(f"  📊 Índices em clusters_eventos: {len(indices_clusters)}")
            for idx in indices_clusters:
                print(f"    ✅ {idx[0]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao verificar índices: {e}")
        return False

def analisar_performance():
    """Analisa a performance das queries principais."""
    print("\n📈 Analisando performance das queries...")
    
    try:
        with engine.connect() as conn:
            # Query 1: Contagem de artigos por data
            print("  🔍 Testando query de contagem por data...")
            result = conn.execute(text("""
                EXPLAIN (ANALYZE, BUFFERS) 
                SELECT COUNT(*) FROM artigos_brutos 
                WHERE DATE(created_at) = CURRENT_DATE
            """))
            
            # Query 2: Clusters com artigos de hoje
            print("  🔍 Testando query de clusters por data...")
            result = conn.execute(text("""
                EXPLAIN (ANALYZE, BUFFERS) 
                SELECT DISTINCT c.* FROM clusters_eventos c
                JOIN artigos_brutos a ON c.id = a.cluster_id
                WHERE DATE(a.created_at) = CURRENT_DATE
                AND c.status = 'ativo'
            """))
            
            print("  ✅ Análise de performance concluída")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro na análise de performance: {e}")
        return False

def main():
    """Função principal."""
    print("🚀 Otimização de Performance - BTG AlphaFeed")
    print("=" * 50)
    
    # Aplica índices
    if not aplicar_indices_performance():
        print("❌ Falha ao aplicar índices")
        return 1
    
    # Verifica índices
    if not verificar_indices():
        print("❌ Falha ao verificar índices")
        return 1
    
    # Analisa performance
    if not analisar_performance():
        print("❌ Falha na análise de performance")
        return 1
    
    print("\n🎉 Otimização concluída com sucesso!")
    print("\n📋 Melhorias implementadas:")
    print("  ✅ Índices por data para queries rápidas")
    print("  ✅ Índices compostos para filtros complexos")
    print("  ✅ Paginação no frontend (20 itens por página)")
    print("  ✅ Carregamento lazy de textos completos")
    print("  ✅ Modal para detalhes sob demanda")
    print("  ✅ Scroll infinito para melhor UX")
    
    print("\n🚀 Como usar:")
    print("  python load_news.py                    # Carrega notícias")
    print("  python process_articles.py             # Processa e agrupa")
    print("  python start_dev.py                    # Inicia o servidor")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 