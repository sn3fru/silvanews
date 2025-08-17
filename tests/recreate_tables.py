#!/usr/bin/env python3
"""
Script para recriar as tabelas com o novo schema corrigido.
"""

import os
import sys
from sqlalchemy import text

# Adiciona o diretório atual ao path para importar os módulos
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.database import engine, SessionLocal

def recreate_tables():
    """Recria as tabelas com o novo schema"""
    print("🔄 Recriando tabelas com novo schema...")
    
    # Drop das tabelas de prompts
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS prompt_prioridade_itens CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS prompt_tags CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS prompt_templates CASCADE"))
        conn.commit()
    
    print("✅ Tabelas antigas removidas")
    
    # Recria as tabelas
    from backend.database import create_tables
    create_tables()
    
    print("✅ Tabelas recriadas com novo schema")
    print("🎯 Agora execute: python seed_prompts.py")

if __name__ == "__main__":
    recreate_tables()
