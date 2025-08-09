#!/usr/bin/env python3
"""
Script principal para executar o fluxo completo do BTG AlphaFeed.
Automatiza: carregamento -> processamento -> clusterização -> resumos -> frontend.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def check_conda_env():
    """Verifica se está no ambiente conda correto."""
    conda_env = os.environ.get('CONDA_DEFAULT_ENV')
    if conda_env != 'pymc2':
        print("AVISO: Você deve ativar o ambiente conda 'pymc2'")
        print("Execute: conda activate pymc2")
        return False
    return True

def check_env_file():
    """Verifica se o arquivo .env existe."""
    env_file = Path(__file__).parent / "backend" / ".env"
    if not env_file.exists():
        print("ERRO: Arquivo .env não encontrado!")
        print(f"Crie o arquivo: {env_file}")
        print("\nConteúdo necessário:")
        print("DATABASE_URL=\"postgresql://user:password@host:port/dbname\"")
        print("GEMINI_API_KEY=\"sua_chave_api\"")
        return False
    return True

def run_load_news():
    """Executa o carregamento de notícias."""
    try:
        print("ETAPA 1: Carregando notícias...")
        
        # Verifica se há arquivos para processar
        pdfs_dir = Path(__file__).parent.parent / "pdfs"
        if not pdfs_dir.exists():
            print(f"ERRO: Diretório de PDFs não encontrado: {pdfs_dir}")
            return False
        
        # Lista arquivos disponíveis
        arquivos = list(pdfs_dir.glob("*.json")) + list(pdfs_dir.glob("*.pdf"))
        if not arquivos:
            print(f"ERRO: Nenhum arquivo encontrado em: {pdfs_dir}")
            return False
        
        print(f"Encontrados {len(arquivos)} arquivos para processar:")
        for arquivo in arquivos[:5]:  # Mostra apenas os primeiros 5
            print(f"   - {arquivo.name}")
        
        # Executa o carregamento
        result = subprocess.run([
            sys.executable, "load_news.py", "--dir", str(pdfs_dir), "--yes"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("SUCESSO: Carregamento de notícias concluído!")
            print(result.stdout)
            return True
        else:
            print("ERRO: Erro no carregamento de notícias:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"ERRO: Erro ao executar carregamento: {e}")
        return False

def run_process_articles():
    """Executa o processamento de artigos."""
    try:
        print("\nETAPA 2: Processando artigos...")
        
        # Executa o processamento
        result = subprocess.run([
            sys.executable, "process_articles.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("SUCESSO: Processamento de artigos concluído!")
            print(result.stdout)
            return True
        else:
            print("ERRO: Erro no processamento de artigos:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"ERRO: Erro ao executar processamento: {e}")
        return False

def run_test_workflow():
    """Executa o teste do fluxo completo."""
    try:
        print("\nETAPA 3: Testando fluxo completo...")
        
        # Executa o teste
        result = subprocess.run([
            sys.executable, "test_fluxo_completo.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("SUCESSO: Teste do fluxo completo concluído!")
            print(result.stdout)
            return True
        else:
            print("ERRO: Erro no teste do fluxo completo:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"ERRO: Erro ao executar teste: {e}")
        return False

def start_backend():
    """Inicia o backend."""
    try:
        print("\nETAPA 4: Iniciando backend...")
        print("Acesse o frontend em: http://localhost:8000/frontend")
        print("API docs em: http://localhost:8000/docs")
        print("Health check: http://localhost:8000/health")
        print("\nPressione Ctrl+C para parar o servidor\n")
        
        # Aguarda um pouco para o usuário ler
        time.sleep(3)
        
        # Inicia o backend
        subprocess.run([
            sys.executable, "start_dev.py"
        ], cwd=Path(__file__).parent)
        
    except KeyboardInterrupt:
        print("\nServidor parado pelo usuário")
    except Exception as e:
        print(f"ERRO: Erro ao iniciar backend: {e}")

def main():
    """Função principal."""
    print("=" * 60)
    print("BTG AlphaFeed - Fluxo Completo Automatizado")
    print("=" * 60)
    
    # Verificações iniciais
    if not check_conda_env():
        sys.exit(1)
    
    if not check_env_file():
        sys.exit(1)
    
    # Pergunta se deve executar o fluxo completo
    print("\nEste script executará:")
    print("   1. Carregamento de notícias (load_news.py)")
    print("   2. Processamento de artigos (process_articles.py)")
    print("   3. Teste do fluxo completo")
    print("   4. Inicialização do backend")
    
    executar = input("\nExecutar fluxo completo? (s/N): ").lower().strip()
    if executar not in ['s', 'sim', 'yes', 'y']:
        print("Processamento cancelado.")
        return
    
    # ETAPA 1: Carregamento de notícias
    if not run_load_news():
        print("ERRO: Falha no carregamento de notícias")
        sys.exit(1)
    
    # ETAPA 2: Processamento de artigos
    if not run_process_articles():
        print("ERRO: Falha no processamento de artigos")
        sys.exit(1)
    
    # ETAPA 3: Teste do fluxo completo
    if not run_test_workflow():
        print("ERRO: Falha no teste do fluxo completo")
        sys.exit(1)
    
    # ETAPA 4: Inicialização do backend
    start_backend()

if __name__ == "__main__":
    main() 