#!/usr/bin/env python3
"""
Script de teste para verificar importações do BTG AlphaFeed.
"""

import sys
from pathlib import Path

print("🔍 Testando importações do BTG AlphaFeed...")

# Adiciona o diretório backend ao path (um nível acima)
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

print(f"📁 Backend dir: {backend_dir}")
print(f"📁 Backend dir existe: {backend_dir.exists()}")

try:
    print("📦 Testando importação do FileLoader...")
    from backend.collectors.file_loader import FileLoader
    print("✅ FileLoader importado com sucesso!")
    
    print("📦 Testando importação do database...")
    from backend.database import SessionLocal
    print("✅ SessionLocal importado com sucesso!")
    
    print("📦 Testando importação do models...")
    from backend.models import ArtigoBrutoCreate
    print("✅ ArtigoBrutoCreate importado com sucesso!")
    
    print("📦 Testando importação do crud...")
    from backend.crud import create_artigo_bruto
    print("✅ create_artigo_bruto importado com sucesso!")

    print("📦 Testando importação do semantic_search...")
    import btg_alphafeed.semantic_search as ss
    assert hasattr(ss, 'semantic_search')
    print("✅ semantic_search importado com sucesso!")
    
    print("\n🎉 Todas as importações funcionaram!")
    print("✅ O sistema está pronto para uso!")
    
except ImportError as e:
    print(f"❌ Erro de importação: {e}")
    print("\n🔧 Soluções possíveis:")
    print("1. Verifique se está no ambiente conda correto: conda activate pymc2")
    print("2. Instale as dependências: pip install -r backend/requirements.txt")
    print("3. Verifique se o arquivo .env está configurado")
    
except Exception as e:
    print(f"❌ Erro inesperado: {e}")
    print(f"Tipo do erro: {type(e)}") 