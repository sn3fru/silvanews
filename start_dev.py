#!/usr/bin/env python3
"""
Script de inicialização para desenvolvimento do BTG AlphaFeed.
Automatiza a configuração inicial e execução do sistema.
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
        print("⚠️  AVISO: Você deve ativar o ambiente conda 'pymc2'")
        print("Execute: conda activate pymc2")
        return False
    return True

def check_env_file():
    """Verifica se o arquivo .env existe."""
    env_file = Path(__file__).parent / "backend" / ".env"
    if not env_file.exists():
        print("❌ Arquivo .env não encontrado!")
        print(f"Crie o arquivo: {env_file}")
        print("\nConteúdo necessário:")
        print("DATABASE_URL=\"postgresql://user:password@host:port/dbname\"")
        print("GEMINI_API_KEY=\"sua_chave_api\"")
        return False
    return True

def install_dependencies():
    """Instala as dependências necessárias."""
    try:
        print("📦 Instalando dependências...")
        backend_dir = Path(__file__).parent / "backend"
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", 
            str(backend_dir / "requirements.txt")
        ], check=True)
        print("✅ Dependências instaladas!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao instalar dependências: {e}")
        return False

def init_database():
    """Inicializa o banco de dados."""
    try:
        print("🗄️  Inicializando banco de dados...")
        backend_dir = Path(__file__).parent / "backend"
        
        # Muda para o diretório backend temporariamente
        original_dir = os.getcwd()
        os.chdir(backend_dir)
        
        # Executa o script de inicialização
        subprocess.run([sys.executable, "database.py"], check=True)
        
        # Volta para o diretório original
        os.chdir(original_dir)
        
        print("✅ Banco de dados inicializado!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao inicializar banco: {e}")
        return False

def start_api():
    """Inicia a API FastAPI da maneira correta, sem mudar de diretório."""
    try:
        print("🚀 Iniciando API BTG AlphaFeed...")
        
        # Define o diretorio raiz do projeto (onde o start.py esta)
        project_root = Path(__file__).parent
        
        # O comando uvicorn agora especifica o caminho do pacote: 'backend.main:app'
        # Isso permite que as importacoes relativas dentro do 'backend' funcionem.
        # Nao usamos mais 'os.chdir'. Em vez disso, informamos ao subprocess
        # qual deve ser seu diretorio de trabalho com o argumento 'cwd'.
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "backend.main:app",  # <--- MUDANCA CRUCIAL
            "--reload", 
            "--host", "0.0.0.0", 
            "--port", "8000"
        ], cwd=project_root) # <--- EXECUTANDO A PARTIR DO DIRETORIO RAIZ

    except KeyboardInterrupt:
        print("\n🛑 Servidor parado pelo usuário")
    except Exception as e:
        print(f"❌ Erro ao iniciar servidor: {e}")

def main():
    """Função principal."""
    print("=" * 50)
    print("🏦 BTG AlphaFeed - Setup de Desenvolvimento")
    print("=" * 50)
    
    # Verificações iniciais
    if not check_conda_env():
        sys.exit(1)
    
    if not check_env_file():
        sys.exit(1)
    
    # Pergunta se deve instalar dependências
    install_deps = input("\n📦 Instalar/atualizar dependências? (s/N): ").lower().strip()
    if install_deps in ['s', 'sim', 'yes', 'y']:
        if not install_dependencies():
            sys.exit(1)
    
    # Pergunta se deve inicializar banco
    init_db = input("\n🗄️  Inicializar banco de dados? (s/N): ").lower().strip()
    if init_db in ['s', 'sim', 'yes', 'y']:
        if not init_database():
            print("⚠️  Falha na inicialização do banco. Continuando...")
    
    print("\n" + "=" * 50)
    print("🌐 Acesse o frontend em: http://localhost:8000/frontend")
    print("📡 API docs em: http://localhost:8000/docs")
    print("❤️  Health check: http://localhost:8000/health")
    print("=" * 50)
    print("\n🎯 Pressione Ctrl+C para parar o servidor\n")
    
    # Aguarda um pouco para o usuário ler
    time.sleep(0.2)
    
    # Inicia a API
    start_api()

if __name__ == "__main__":
    main()