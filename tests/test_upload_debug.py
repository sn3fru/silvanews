#!/usr/bin/env python3
"""
Script de teste para verificar se o upload de arquivos está funcionando corretamente.
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.collectors.file_loader import FileLoader
from backend.database import SessionLocal
from backend.crud import get_artigos_pendentes, create_log

def test_file_loader():
    """Testa o FileLoader com logs detalhados."""
    print("=" * 80)
    print("🧪 TESTE DO FILE LOADER")
    print("=" * 80)
    
    # Cria instância do carregador
    loader = FileLoader(
        api_base_url="http://localhost:8000",
        files_directory="../pdfs"
    )
    
    print(f"📁 Diretório configurado: {loader.files_directory}")
    print(f"🌐 API URL: {loader.api_base_url}")
    
    # Verifica se o diretório existe
    if not loader.files_directory.exists():
        print(f"❌ ERRO: Diretório {loader.files_directory} não encontrado!")
        return False
    
    # Lista arquivos disponíveis
    arquivos_json = list(loader.files_directory.glob("*.json"))
    arquivos_pdf = list(loader.files_directory.glob("*.pdf"))
    
    print(f"📊 Arquivos encontrados:")
    print(f"   📄 JSONs: {len(arquivos_json)}")
    for arquivo in arquivos_json:
        print(f"     - {arquivo.name}")
    
    print(f"   📰 PDFs: {len(arquivos_pdf)}")
    for arquivo in arquivos_pdf:
        print(f"     - {arquivo.name}")
    
    if not arquivos_json and not arquivos_pdf:
        print("❌ Nenhum arquivo para testar!")
        return False
    
    # Testa processamento de um arquivo
    arquivo_teste = None
    if arquivos_json:
        arquivo_teste = arquivos_json[0]
        print(f"\n🧪 Testando JSON: {arquivo_teste.name}")
    elif arquivos_pdf:
        arquivo_teste = arquivos_pdf[0]
        print(f"\n🧪 Testando PDF: {arquivo_teste.name}")
    
    if arquivo_teste:
        try:
            # Processa arquivo
            artigos = loader.processar_arquivo(arquivo_teste, usar_api=False)
            print(f"✅ Arquivo processado: {artigos} artigos")
            
            # Verifica se foram criados no banco
            db = SessionLocal()
            try:
                artigos_pendentes = get_artigos_pendentes(db, limite=10)
                print(f"📊 Artigos pendentes no banco: {len(artigos_pendentes)}")
                
                if artigos_pendentes:
                    print("📋 Últimos artigos criados:")
                    for i, artigo in enumerate(artigos_pendentes[:5], 1):
                        print(f"   {i}. ID: {artigo.id}")
                        print(f"      Título: {artigo.titulo_extraido or 'N/A'}")
                        print(f"      Jornal: {artigo.jornal or 'N/A'}")
                        print(f"      Status: {artigo.status}")
                        print(f"      Criado: {artigo.created_at}")
                        print()
                
            finally:
                db.close()
            
            return True
            
        except Exception as e:
            print(f"❌ ERRO no teste: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return False

def test_database_connection():
    """Testa a conexão com o banco de dados."""
    print("\n" + "=" * 80)
    print("🗄️ TESTE DE CONEXÃO COM BANCO")
    print("=" * 80)
    
    try:
        db = SessionLocal()
        
        # Testa query simples
        from backend.crud import get_database_stats
        stats = get_database_stats(db)
        
        print("✅ Conexão com banco OK")
        print(f"📊 Estatísticas do banco:")
        print(f"   📰 Artigos brutos: {stats.get('artigos_brutos', 0)}")
        print(f"   🔗 Clusters: {stats.get('clusters', 0)}")
        print(f"   📝 Logs: {stats.get('logs', 0)}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ ERRO na conexão com banco: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Função principal do teste."""
    print("🚀 Iniciando testes de upload...")
    
    # Testa conexão com banco
    if not test_database_connection():
        print("❌ Falha no teste de conexão com banco")
        return 1
    
    # Testa file loader
    if not test_file_loader():
        print("❌ Falha no teste do file loader")
        return 1
    
    print("\n" + "=" * 80)
    print("🎉 TODOS OS TESTES PASSARAM!")
    print("=" * 80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 