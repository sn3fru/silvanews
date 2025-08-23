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

def check_and_start_local_db():
    """Verifica se o banco local está rodando e inicia se necessário."""
    try:
        print("ETAPA 0: Verificando banco de dados local...")
        
        # Configurações do banco local (hardcoded para evitar parâmetros)
        DB_HOST = "localhost"
        DB_PORT = "5433"
        DB_NAME = "devdb"
        DB_USER = "postgres_local"
        DB_PASSWORD = "postgres"
        
        # Tenta conectar com o banco local
        import psycopg2
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            conn.close()
            print("✅ Banco de dados local já está rodando!")
            return True
        except psycopg2.OperationalError:
            print("⚠️ Banco local não está rodando. Tentando iniciar...")
        
        # Busca o diretório do PostgreSQL de forma automática
        possible_paths = [
            Path("C:/Users/marcos.silva/postgresql-17.5-3"),
            # Path("C:/postgresql-17.5-3"),
            # Path("C:/Program Files/PostgreSQL/17.5"),
            # Path("C:/Program Files (x86)/PostgreSQL/17.5")
        ]
        
        postgres_dir = None
        start_db_script = None
        
        for path in possible_paths:
            if path.exists():
                script_path = path / "start_db.cmd"
                if script_path.exists():
                    postgres_dir = path
                    start_db_script = script_path
                    break
        
        if not start_db_script:
            print("❌ Script start_db.cmd não encontrado nos diretórios padrão:")
            for path in possible_paths:
                print(f"   - {path}")
            print("\nPor favor, inicie manualmente o banco de dados local")
            print("Execute: start_db.cmd no diretório do PostgreSQL")
            return False
        
        print(f"🚀 Iniciando banco de dados local...")
        print(f"Executando: {start_db_script}")
        
        # Executa o script de inicialização
        result = subprocess.run([
            str(start_db_script)
        ], cwd=postgres_dir, capture_output=True, text=True, shell=True)
        
        if result.returncode == 0:
            print("✅ Banco de dados local iniciado com sucesso!")
            
            # Aguarda um pouco para o banco inicializar
            print("⏳ Aguardando inicialização do banco...")
            time.sleep(5)
            
            # Testa conexão novamente
            try:
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                conn.close()
                print("✅ Conexão com banco local estabelecida!")
                return True
            except psycopg2.OperationalError as e:
                print(f"❌ Falha ao conectar com banco local após inicialização: {e}")
                return False
        else:
            print(f"❌ Erro ao iniciar banco local: {result.stderr}")
            return False
            
    except ImportError:
        print("⚠️ psycopg2 não disponível. Pulando verificação de banco local.")
        print("Certifique-se de que o banco local está rodando antes de continuar.")
        return True
    except Exception as e:
        print(f"❌ Erro ao verificar/iniciar banco local: {e}")
        return False

def run_load_news():
    """Executa o carregamento de notícias."""
    try:
        print("ETAPA 1: Carregando notícias...")
        
        # Diretório de PDFs hardcoded (relativo ao diretório pai)
        pdfs_dir = Path(__file__).parent.parent / "pdfs"
        
        if not pdfs_dir.exists():
            print(f"❌ ERRO: Diretório de PDFs não encontrado: {pdfs_dir}")
            print("Certifique-se de que existe uma pasta 'pdfs' no diretório pai")
            return False
        
        # Lista arquivos disponíveis
        arquivos = list(pdfs_dir.glob("*.json")) + list(pdfs_dir.glob("*.pdf"))
        if not arquivos:
            print(f"⚠️ AVISO: Nenhum arquivo encontrado em: {pdfs_dir}")
            print("Coloque arquivos .pdf ou .json na pasta 'pdfs' antes de executar")
            return False
        
        print(f"📁 Encontrados {len(arquivos)} arquivos para processar:")
        for arquivo in arquivos[:5]:  # Mostra apenas os primeiros 5
            print(f"   - {arquivo.name}")
        if len(arquivos) > 5:
            print(f"   ... e mais {len(arquivos) - 5} arquivos")
        
        # Executa o carregamento com parâmetros hardcoded
        print(f"🚀 Executando: python load_news.py --dir {pdfs_dir} --direct --yes")
        result = subprocess.run([
            sys.executable, "load_news.py", "--dir", str(pdfs_dir), "--direct", "--yes"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ SUCESSO: Carregamento de notícias concluído!")
            print(result.stdout)
            return True
        else:
            print("❌ ERRO: Erro no carregamento de notícias:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ ERRO: Erro ao executar carregamento: {e}")
        return False

def run_process_articles():
    """Executa o processamento de artigos."""
    try:
        print("\nETAPA 2: Processando artigos...")
        
        # Executa o processamento com comando hardcoded
        print("🚀 Executando: python process_articles.py")
        result = subprocess.run([
            sys.executable, "process_articles.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ SUCESSO: Processamento de artigos concluído!")
            print(result.stdout)
            return True
        else:
            print("❌ ERRO: Erro no processamento de artigos:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ ERRO: Erro ao executar processamento: {e}")
        return False

def run_migrate_incremental():
    """Executa a migração incremental do banco de dados."""
    try:
        print("\nETAPA 3: Executando migração incremental do banco...")
        
        # Configurações de conexão (hardcoded para evitar parâmetros)
        SOURCE_DB = "postgresql+psycopg2://postgres_local@localhost:5433/devdb"
        DEST_DB = "postgres://u71uif3ajf4qqh:pbfa5924f245d80b107c9fb38d5496afc0c1372a3f163959faa933e5b9f7c47d6@c3v5n5ajfopshl.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/daoetg9ahbmcff"
        
        print(f"Origem: {SOURCE_DB}")
        print(f"Destino: {DEST_DB}")
        
        # Executa a migração com comando exato especificado
        result = subprocess.run([
            sys.executable, "-m", "migrate_incremental", 
            "--source", SOURCE_DB,
            "--dest", DEST_DB,
            "--include-logs", "--include-chat"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ SUCESSO: Migração incremental concluída!")
            print(result.stdout)
            return True
        else:
            print("❌ ERRO: Erro na migração incremental:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ ERRO: Erro ao executar migração: {e}")
        return False

def run_test_workflow():
    """Executa o teste do fluxo completo."""
    try:
        print("\nETAPA 4: Testando fluxo completo...")
        
        # Executa o teste com comando hardcoded
        print("🚀 Executando: python test_fluxo_completo.py")
        result = subprocess.run([
            sys.executable, "test_fluxo_completo.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ SUCESSO: Teste do fluxo completo concluído!")
            print(result.stdout)
            return True
        else:
            print("❌ ERRO: Erro no teste do fluxo completo:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ ERRO: Erro ao executar teste: {e}")
        return False

def start_backend():
    """Inicia o backend."""
    try:
        print("\nETAPA 5: Iniciando backend...")
        print("🌐 Acesse o frontend em: http://localhost:8000/frontend")
        print("📚 API docs em: http://localhost:8000/docs")
        print("💚 Health check: http://localhost:8000/health")
        print("\n⏹️ Pressione Ctrl+C para parar o servidor\n")
        
        # Aguarda um pouco para o usuário ler
        time.sleep(0.3)
        
        # Inicia o backend com comando hardcoded
        print("🚀 Executando: python start_dev.py")
        subprocess.run([
            sys.executable, "start_dev.py"
        ], cwd=Path(__file__).parent)
        
    except KeyboardInterrupt:
        print("\n🛑 Servidor parado pelo usuário")
    except Exception as e:
        print(f"❌ ERRO: Erro ao iniciar backend: {e}")

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
    
    # ETAPA 0: Verifica e inicia banco local se necessário
    if not check_and_start_local_db():
        print("❌ Falha na verificação/inicialização do banco local")
        sys.exit(1)
    
    # Pergunta se deve executar o fluxo completo
    print("\nEste script executará:")
    print("   0. ✅ Verificação/inicialização do banco local")
    print("   1. Carregamento de notícias (load_news.py --direct --yes)")
    print("   2. Processamento de artigos (process_articles.py)")
    print("   3. Migração incremental do banco (migrate_incremental)")
    print("   4. Teste do fluxo completo")
    print("   5. Inicialização do backend")
    
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
    
    # ETAPA 3: Migração incremental do banco
    if not run_migrate_incremental():
        print("ERRO: Falha na migração incremental")
        sys.exit(1)
    
    # ETAPA 4: Teste do fluxo completo
    if not run_test_workflow():
        print("ERRO: Falha no teste do fluxo completo")
        sys.exit(1)
    
    # ETAPA 5: Inicialização do backend
    start_backend()

if __name__ == "__main__":
    main() 