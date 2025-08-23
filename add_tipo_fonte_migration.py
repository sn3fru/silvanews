#!/usr/bin/env python3
"""
Script de migração para adicionar a coluna tipo_fonte nas tabelas
artigos_brutos e clusters_eventos.
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.database import engine

def run_migration():
    """Executa a migração para adicionar tipo_fonte."""
    
    print("🔄 Iniciando migração para adicionar tipo_fonte...")
    
    with engine.begin() as conn:
        try:
            # Adiciona coluna tipo_fonte na tabela artigos_brutos
            print("📊 Adicionando coluna tipo_fonte em artigos_brutos...")
            conn.execute(text("""
                ALTER TABLE artigos_brutos 
                ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
            """))
            print("✅ Coluna tipo_fonte adicionada em artigos_brutos")
            
            # Adiciona coluna tipo_fonte na tabela clusters_eventos
            print("📊 Adicionando coluna tipo_fonte em clusters_eventos...")
            conn.execute(text("""
                ALTER TABLE clusters_eventos 
                ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
            """))
            print("✅ Coluna tipo_fonte adicionada em clusters_eventos")
            
            # Cria índice para performance
            print("📊 Criando índices...")
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_artigos_tipo_fonte 
                ON artigos_brutos(tipo_fonte);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_clusters_tipo_fonte 
                ON clusters_eventos(tipo_fonte);
            """))
            print("✅ Índices criados com sucesso")
            
            print("\n🎉 Migração concluída com sucesso!")
            
        except Exception as e:
            print(f"\n❌ Erro durante a migração: {e}")
            raise

if __name__ == "__main__":
    run_migration()
