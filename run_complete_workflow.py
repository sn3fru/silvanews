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

# Fix Windows encoding issues
if os.name == 'nt':
    try:
        # Force UTF-8 mode for Windows
        os.environ["PYTHONUTF8"] = "1"
        # Alternative: set console to UTF-8
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass

# URL do banco de produção (usada na migração e no resumo diário)
PRODUCTION_DATABASE_URL = "postgres://u71uif3ajf4qqh:pbfa5924f245d80b107c9fb38d5496afc0c1372a3f163959faa933e5b9f7c47d6@c3v5n5ajfopshl.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/daoetg9ahbmcff"

def check_conda_env():
    """Verifica se está no ambiente conda correto."""
    conda_env = os.environ.get('CONDA_DEFAULT_ENV')
    if conda_env != 'pymc2':
        print("AVISO: Você deve ativar o ambiente conda 'pymc2'")
        print("Execute: conda activate pymc2")
        return False
    return True

def _subprocess_env():
    """Ambiente para forçar UTF-8 nos subprocessos (evita erro cp1252 no Windows)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Força encoding UTF-8 no Windows
    if os.name == 'nt':
        env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8"
    # Injeta variáveis do arquivo backend/.env para subprocessos
    try:
        from dotenv import dotenv_values
        env_file = Path(__file__).parent / "backend" / ".env"
        if env_file.exists():
            env_vars = dotenv_values(env_file)
            # Prioriza valores do .env quando não estão setados no ambiente atual
            for key, value in (env_vars or {}).items():
                if value is None:
                    continue
                if not env.get(key):
                    env[key] = value
    except Exception:
        # Falha silenciosa: continuará com env atual
        pass
    
    return env

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
        print("  Verificando banco de dados local...")
        
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
            print("[OK] Banco de dados local já está rodando!")
            return True
        except psycopg2.OperationalError:
            print("[INFO] Banco local não está rodando. Tentando iniciar...")
        
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
            print("[ERRO] Script start_db.cmd não encontrado nos diretórios padrão:")
            for path in possible_paths:
                print(f"   - {path}")
            print("\nPor favor, inicie manualmente o banco de dados local")
            print("Execute: start_db.cmd no diretório do PostgreSQL")
            return False
        
        print(f"[INFO] Iniciando banco de dados local...")
        print(f"Executando: {start_db_script}")
        
        # Executa o script de inicialização
        result = subprocess.run([
            str(start_db_script)
        ], cwd=postgres_dir, capture_output=True, text=True, shell=True)
        
        if result.returncode == 0:
            print("[OK] Banco de dados local iniciado com sucesso!")
            
            # Aguarda um pouco para o banco inicializar
            print("Aguardando inicialização do banco...")
            time.sleep(5)
            
            # Tenta conectar novamente
            try:
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                conn.close()
                print("[OK] Conexão com banco local estabelecida!")
                return True
            except Exception as e:
                print(f"[ERRO] Falha ao conectar com banco local após inicialização: {e}")
                return False
        else:
            print(f"[ERRO] Erro ao iniciar banco local: {result.stderr}")
            return False
            
    except ImportError:
        print("[INFO] psycopg2 não disponível. Pulando verificação de banco local.")
        return True
    except Exception as e:
        print(f"[ERRO] Erro ao verificar/iniciar banco local: {e}")
        return False

def run_crawlers():
    """ETAPA 0.5: Roda crawlers de noticias online e copia dump.json para pasta pdfs.

    Fluxo:
      1. Executa CRAWLERS/src/news_manager.py (roda cada crawler + gera dump global)
      2. Procura o dump mais recente em CRAWLERS/dump/
      3. Copia para ../pdfs/ (mesma pasta que load_news.py le)

    Se os crawlers falharem, tenta copiar dumps existentes de rodadas anteriores.
    """
    try:
        project_root = Path(__file__).parent
        crawlers_src = project_root / "CRAWLERS" / "src"
        news_manager = crawlers_src / "news_manager.py"
        pdfs_dir = project_root.parent / "pdfs"
        dump_dir = project_root / "CRAWLERS" / "dump"

        if not news_manager.exists():
            print("[CRAWLERS] CRAWLERS/src/news_manager.py nao encontrado. Pulando.")
            return True

        print("\n" + "=" * 60)
        print("  ETAPA 0.5: CRAWLERS DE NOTICIAS ONLINE")
        print("=" * 60)
        print(f"  Script: {news_manager}")
        print(f"  CWD: {crawlers_src}")

        crawlers_ok = False
        try:
            result = subprocess.run(
                [sys.executable, str(news_manager)],
                cwd=str(crawlers_src),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                env=_subprocess_env(),
                timeout=600,
            )
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-10:]:
                    print(f"  | {line}")
            if result.returncode == 0:
                crawlers_ok = True
                print("[CRAWLERS] Crawlers concluidos com sucesso.")
            else:
                print(f"[CRAWLERS] Crawlers falharam (code={result.returncode})")
                if result.stderr:
                    print(f"  stderr: {result.stderr[:300]}")
                print("[CRAWLERS] Tentando copiar dump existente...")

        except subprocess.TimeoutExpired:
            print("[CRAWLERS] Timeout (600s). Tentando copiar dump existente...")
        except Exception as e:
            print(f"[CRAWLERS] Erro ao rodar crawlers: {e}")
            print("[CRAWLERS] Tentando copiar dump existente...")

        # Mesmo se crawlers falharam, tenta copiar o dump mais recente
        if not dump_dir.exists():
            print("[CRAWLERS] Pasta CRAWLERS/dump/ nao existe. Nada a copiar.")
            return crawlers_ok

        from datetime import datetime as dt_mod
        data_hoje = dt_mod.today().strftime("%Y%m%d")
        dump_hoje = dump_dir / f"dump_crawlers_{data_hoje}.json"

        if dump_hoje.exists():
            dump_file = dump_hoje
        else:
            all_dumps = sorted(dump_dir.glob("dump_crawlers_*.json"), reverse=True)
            dump_file = all_dumps[0] if all_dumps else None

        if not dump_file or not dump_file.exists():
            print("[CRAWLERS] Nenhum dump encontrado em CRAWLERS/dump/.")
            return crawlers_ok

        # Verifica tamanho do dump (um dump vazio/corrompido nao serve)
        dump_size = dump_file.stat().st_size
        if dump_size < 100:
            print(f"[CRAWLERS] Dump {dump_file.name} muito pequeno ({dump_size} bytes). Ignorando.")
            return crawlers_ok

        pdfs_dir.mkdir(parents=True, exist_ok=True)
        dest = pdfs_dir / dump_file.name

        if dest.exists():
            print(f"[CRAWLERS] Dump ja existe em pdfs/: {dest.name} ({dump_size:,} bytes)")
        else:
            import shutil
            shutil.copy2(str(dump_file), str(dest))
            print(f"[CRAWLERS] Dump copiado: {dump_file.name} ({dump_size:,} bytes) -> {pdfs_dir}")

        return True

    except Exception as e:
        import traceback
        print(f"[CRAWLERS] Erro inesperado: {e}")
        traceback.print_exc()
        return False


def _filter_subprocess_output(stdout: str, stderr: str, show_errors: bool = True) -> str:
    """Filtra output de subprocessos: mostra apenas linhas relevantes (consolidados e erros)."""
    lines = []
    for line in (stdout or "").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Pular linhas excessivamente verbosas
        if any(skip in stripped for skip in [
            "Enviando artigo", "salvo no banco", "SUCESSO: Artigo criado",
            "Processando página", "Enviando '", "para extração via Gemini",
            "notícias candidatas extraídas", "Fallback: extração simples",
            "Amostra da resposta", "prompts.py:", "Módulos para processamento",
            "Cliente Gemini", "Modo de envio", "DEBUG:",
            "Processando diretório completo", "Iniciando processamento",
            "Próximo passo", "Processando arquivo:",
        ]):
            continue
        lines.append(f"  {stripped}")
    if show_errors and stderr:
        for line in stderr.strip().split("\n"):
            stripped = line.strip()
            if stripped and "DEBUG:" not in stripped:
                lines.append(f"  [stderr] {stripped}")
    return "\n".join(lines[-40:])  # Ultimas 40 linhas relevantes


def run_load_news():
    """Executa o carregamento de noticias.

    Apos ingestao bem-sucedida, move os arquivos para pdfs/processados/
    para evitar re-processamento em execucoes futuras.
    """
    try:
        pdfs_dir = Path(__file__).parent.parent / "pdfs"

        if not pdfs_dir.exists():
            print(f"  [ERRO] Diretorio de PDFs nao encontrado: {pdfs_dir}")
            return False

        arquivos = list(pdfs_dir.glob("*.json")) + list(pdfs_dir.glob("*.pdf"))
        if not arquivos:
            print(f"  [INFO] Nenhum arquivo novo em {pdfs_dir}. Pulando ingestao.")
            return True  # Nao e erro — pode ser que os crawlers nao geraram nada

        print(f"\n{'=' * 60}")
        print(f"  ETAPA 1: INGESTAO DE NOTICIAS")
        print(f"{'=' * 60}")
        print(f"  Arquivos: {len(arquivos)} ({sum(1 for a in arquivos if a.suffix=='.pdf')} PDFs, {sum(1 for a in arquivos if a.suffix=='.json')} JSONs)")
        for arquivo in arquivos[:5]:
            print(f"    - {arquivo.name}")
        if len(arquivos) > 5:
            print(f"    ... +{len(arquivos) - 5} arquivos")

        result = subprocess.run([
            sys.executable, "load_news.py", "--dir", str(pdfs_dir), "--direct", "--yes"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=_subprocess_env())

        filtered = _filter_subprocess_output(result.stdout, result.stderr if result.returncode != 0 else "")
        if filtered.strip():
            print(filtered)

        if result.returncode == 0:
            # Move arquivos processados para subpasta (evita re-processamento)
            processados_dir = pdfs_dir / "processados"
            processados_dir.mkdir(exist_ok=True)
            moved = 0
            for arq in arquivos:
                try:
                    dest = processados_dir / arq.name
                    if dest.exists():
                        dest = processados_dir / f"{arq.stem}_{int(time.time())}{arq.suffix}"
                    arq.rename(dest)
                    moved += 1
                except Exception as e:
                    print(f"  [AVISO] Falha ao mover {arq.name}: {e}")
            if moved:
                print(f"  [OK] Ingestao concluida. {moved} arquivos movidos para processados/")
            else:
                print("  [OK] Ingestao concluida.")
            return True
        else:
            print("  [ERRO] Falha na ingestao.")
            return False

    except Exception as e:
        print(f"  [ERRO] {e}")
        return False

def run_process_articles():
    """Executa o processamento de artigos."""
    try:
        print(f"\n{'=' * 60}")
        print(f"  ETAPA 2: PROCESSAMENTO DE ARTIGOS")
        print(f"{'=' * 60}")

        result = subprocess.run([
            sys.executable, "process_articles.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=_subprocess_env())

        filtered = _filter_subprocess_output(result.stdout, result.stderr if result.returncode != 0 else "")
        if filtered.strip():
            print(filtered)

        if result.returncode == 0:
            print("  [OK] Processamento concluido.")
            return True
        else:
            print("  [ERRO] Falha no processamento.")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    print(f"  [stderr] {line.strip()}")
            return False

    except Exception as e:
        print(f"  [ERRO] {e}")
        return False

def run_migrate_incremental():
    """Executa a migracao incremental do banco de dados."""
    try:
        print(f"\n{'=' * 60}")
        print(f"  ETAPA 4: MIGRACAO LOCAL → PRODUCAO")
        print(f"{'=' * 60}")

        SOURCE_DB = "postgresql+psycopg2://postgres_local@localhost:5433/devdb"
        DEST_DB = PRODUCTION_DATABASE_URL

        dest_host = DEST_DB.split("@")[-1].split("/")[0] if "@" in DEST_DB else "???"
        print(f"  Origem: localhost:5433/devdb")
        print(f"  Destino: {dest_host}")
        
        result = subprocess.run([
            sys.executable, "-m", "migrate_incremental", 
            "--source", SOURCE_DB,
            "--dest", DEST_DB,
            "--include-all"
        ], cwd=Path(__file__).parent, capture_output=False, text=True, encoding='utf-8', errors='replace', env=_subprocess_env())
        
        if result.returncode == 0:
            print("  [OK] Migracao concluida.")
            return True
        else:
            print("  [ERRO] Falha na migracao.")
            return False

    except Exception as e:
        print(f"  [ERRO] {e}")
        return False

def run_test_workflow():
    """Executa o teste do fluxo completo."""
    try:
        print("\nETAPA 4: Testando fluxo completo...")
        
        # Executa o teste com comando hardcoded
        print("[INFO] Executando: python test_fluxo_completo.py")
        result = subprocess.run([
            sys.executable, "test_fluxo_completo.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=_subprocess_env())
        
        if result.returncode == 0:
            print("[OK] SUCESSO: Teste do fluxo completo concluído!")
            print(result.stdout)
            return True
        else:
            print("[ERRO] ERRO: Erro no teste do fluxo completo:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"[ERRO] ERRO: Erro ao executar teste: {e}")
        return False

def start_backend():
    """Inicia o backend."""
    try:
        print("\nETAPA 5: Iniciando backend...")
        print("Acesse o frontend em: http://localhost:8000/frontend")
        print("API docs em: http://localhost:8000/docs")
        print("Health check: http://localhost:8000/health")
        print("\nPressione Ctrl+C para parar o servidor\n")
        
        # Aguarda um pouco para o usuário ler
        time.sleep(0.3)
        
        # Inicia o backend com comando hardcoded
        print("[INFO] Executando: python start_dev.py")
        subprocess.run([
            sys.executable, "start_dev.py"
        ], cwd=Path(__file__).parent, env=_subprocess_env())
        
    except KeyboardInterrupt:
        print("\nServidor parado pelo usuário")
    except Exception as e:
        print(f"[ERRO] ERRO: Erro ao iniciar backend: {e}")

def run_feedback_learning():
    """
    Analisa feedback historico (likes/dislikes) e atualiza regras
    de refinamento para injecao conservadora nos prompts.
    Roda ANTES do processamento para que as regras atualizadas
    estejam disponiveis durante a classificacao (Etapa 3 e 4).
    Nao bloqueia o pipeline em caso de falha.
    """
    try:
        print("\n📊 Feedback Learning: Analisando padroes de likes/dislikes...")
        
        result = subprocess.run([
            sys.executable, "scripts/analyze_feedback.py",
            "--days", "90",
            "--min-samples", "3",
            "--save"
        ], cwd=Path(__file__).parent, capture_output=True, text=True,
        encoding='utf-8', errors='replace', env=_subprocess_env())
        
        if result.returncode == 0:
            print("[OK] Feedback Learning: regras atualizadas")
            # Mostra resumo se houver
            for line in (result.stdout or "").split("\n"):
                if "regra" in line.lower() or "dislike" in line.lower() or "pattern" in line.lower():
                    print(f"  {line.strip()}")
            return True
        else:
            print("[AVISO] Feedback Learning falhou (nao critico):")
            if result.stderr:
                print(f"  {result.stderr[:200]}")
            return True  # Nao bloqueia pipeline
            
    except Exception as e:
        print(f"[AVISO] Feedback Learning indisponivel: {e}")
        return True  # Nao bloqueia pipeline


def run_cleanup(days: int = 90):
    """Remove artigos e clusters com mais de N dias. Preserva resumos do dia."""
    try:
        print(f"CLEANUP: Removendo dados com mais de {days} dias...")
        from backend.database import SessionLocal
        from backend.crud import cleanup_old_data as _cleanup

        db = SessionLocal()
        try:
            stats = _cleanup(db, days=days)
            total = sum(stats.values())
            if total > 0:
                print(f"[CLEANUP] Removidos: {stats['artigos_deleted']} artigos, "
                      f"{stats['clusters_deleted']} clusters, {stats['chat_deleted']} chats")
            else:
                print("[CLEANUP] Nenhum dado antigo para remover.")
        finally:
            db.close()
    except Exception as e:
        print(f"[CLEANUP] Erro: {e}")


def run_notify():
    """Envia notificacoes Telegram de clusters pendentes (notificacoes individuais)."""
    try:
        print("\nETAPA 4: Enviando notificacoes Telegram...")
        
        # Verifica se tem config de Telegram
        env = _subprocess_env()
        if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
            print("[INFO] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nao configurados. Pulando notificacoes.")
            return True  # Nao falha, apenas pula
        
        print("[INFO] Executando: python scripts/notify_telegram.py")
        result = subprocess.run([
            sys.executable, "scripts/notify_telegram.py", "--limit", "50"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        
        if result.returncode == 0:
            print("[OK] Notificacoes enviadas!")
            print(result.stdout)
            return True
        else:
            print("[AVISO] Erro nas notificacoes (nao critico):")
            print(result.stderr)
            return True  # Nao bloqueia pipeline
            
    except Exception as e:
        print(f"[AVISO] Erro ao enviar notificacoes: {e}")
        return True  # Nao bloqueia pipeline


def run_telegram_briefing():
    """
    ETAPA 5: Gera e envia Daily Briefing sintetizado via Telegram.
    Usa o TelegramBroadcaster (backend/broadcaster.py) que:
      1. Busca clusters P1/P2 do dia
      2. Gera briefing via Gemini Flash
      3. Envia para canal Telegram
    Idempotente: nao reenvia se ja enviou hoje.
    Nao bloqueia o pipeline em caso de falha.
    """
    try:
        print("\nETAPA 5: Gerando Daily Briefing (Telegram)...")
        
        # Verifica configuracao
        env = _subprocess_env()
        if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
            print("[INFO] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nao configurados. Pulando briefing.")
            return True
        
        print("[INFO] Executando: python send_telegram.py")
        result = subprocess.run([
            sys.executable, "send_telegram.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        
        if result.returncode == 0:
            print("[OK] Daily Briefing enviado!")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print("[AVISO] Erro no briefing (nao critico):")
            if result.stderr:
                print(result.stderr)
            if result.stdout:
                print(result.stdout)
            return True  # Nao bloqueia pipeline
            
    except Exception as e:
        print(f"[AVISO] Erro ao gerar briefing: {e}")
        return True  # Nao bloqueia pipeline


def run_resumo_diario():
    """
    Gera o resumo do dia (multi-persona) e imprime no terminal formatado para WhatsApp.
    Usa o banco LOCAL (dados ja processados, antes da migracao).
    Nao bloqueia o pipeline em caso de falha.
    """
    try:
        print("\n" + "=" * 60)
        print("  RESUMO DO DIA — Multi-Persona (WhatsApp)")
        print("=" * 60)

        from agents.resumo_diario.agent import gerar_resumo_diario, formatar_whatsapp
        from backend.prompts import PERSONAS_RESUMO_DIARIO
        from backend.utils import get_date_brasil

        target_date = get_date_brasil()
        print(f"  Data: {target_date.isoformat()}")
        print(f"  Personas: {list(PERSONAS_RESUMO_DIARIO.keys())}")
        print()

        resultado = gerar_resumo_diario(target_date=target_date)

        if not resultado.get("ok"):
            print(f"[AVISO] Resumo falhou: {resultado.get('error', 'desconhecido')}")
            return True

        # Formata e imprime no terminal
        mensagens = formatar_whatsapp(resultado)
        print("\n" + "-" * 60)
        print("  MENSAGEM WHATSAPP (pronta para enviar):")
        print("-" * 60)
        for msg in mensagens:
            print(msg)
            print()

        # Resumo estatistico
        total = len(resultado.get("todos_clusters_escolhidos_ids", []))
        avaliados = len(resultado.get("clusters_avaliados_ids", []))
        print(f"[OK] Resumo gerado: {total} clusters selecionados de {avaliados} avaliados.")
        return True

    except Exception as e:
        print(f"[AVISO] Erro ao gerar resumo do dia: {e}")
        import traceback
        traceback.print_exc()
        return True


_MICROBATCH_LOCK_FILE = ".microbatch.lock"


def _acquire_lock(lock_path: Path) -> bool:
    """Tenta adquirir lock file. Retorna False se ja existe um processo ativo."""
    if lock_path.exists():
        try:
            content = lock_path.read_text().strip()
            pid = int(content.split("|")[0])
            import psutil
            if psutil.pid_exists(pid):
                print(f"[Lock] Processo {pid} ainda ativo. Abortando este ciclo.")
                return False
            else:
                print(f"[Lock] PID {pid} morto. Removendo lock stale.")
                lock_path.unlink(missing_ok=True)
        except (ImportError, ValueError, OSError):
            age = time.time() - lock_path.stat().st_mtime
            if age < 600:  # 10min safety
                print(f"[Lock] Lock file existe ({age:.0f}s). Abortando.")
                return False
            print(f"[Lock] Lock file stale ({age:.0f}s). Removendo.")
            lock_path.unlink(missing_ok=True)
    lock_path.write_text(f"{os.getpid()}|{time.strftime('%Y-%m-%d %H:%M:%S')}")
    return True


def _release_lock(lock_path: Path):
    """Libera lock file."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def run_microbatch_cycle(pdfs_dir: str = None, batch_interval_minutes: int = 3):
    """
    Processa PDFs em micro-lotes: acumula por N minutos, processa o lote inteiro de uma vez.
    Evita o overhead de levantar um subprocess por PDF individual.
    Reutiliza conexoes e modelos carregados.

    Protecao contra race condition: usa lock file para evitar sobreposicao de ciclos.
    Se o lock estiver ativo, o ciclo é abortado e espera o proximo intervalo.
    """
    if pdfs_dir is None:
        pdfs_dir = str(Path(__file__).parent.parent / "pdfs")

    pdfs_path = Path(pdfs_dir)
    processed_dir = pdfs_path / "_processed"
    processed_dir.mkdir(exist_ok=True)
    lock_path = pdfs_path / _MICROBATCH_LOCK_FILE

    print(f"\n{'='*60}")
    print(f"  MICRO-BATCH PIPELINE (intervalo: {batch_interval_minutes} min)")
    print(f"  Diretório monitorado: {pdfs_path}")
    print(f"{'='*60}")

    ciclo = 0
    try:
        while True:
            ciclo += 1

            if not _acquire_lock(lock_path):
                print(f"[Micro-batch #{ciclo}] Ciclo anterior ainda ativo. Pulando.")
                time.sleep(batch_interval_minutes * 60)
                continue

            try:
                pending = sorted(pdfs_path.glob("*.pdf"))
                if not pending:
                    print(f"[Micro-batch #{ciclo}] Nenhum PDF pendente. Aguardando {batch_interval_minutes} min...")
                    time.sleep(batch_interval_minutes * 60)
                    continue

                print(f"\n[Micro-batch #{ciclo}] {len(pending)} PDFs encontrados. Processando lote...")

                if not run_load_news():
                    print("[AVISO] Falha no carregamento (continuando...)")

                if not run_process_articles():
                    print("[AVISO] Falha no processamento (continuando...)")

                for pdf in pending:
                    try:
                        dest = processed_dir / pdf.name
                        pdf.rename(dest)
                    except Exception as e:
                        print(f"[AVISO] Falha ao mover {pdf.name}: {e}")

                run_migrate_incremental()
                run_notify()

                if ciclo % 10 == 0:
                    run_cleanup(days=90)

                print(f"[Micro-batch #{ciclo}] Lote concluido. {len(pending)} PDFs processados.")
                print(f"Aguardando {batch_interval_minutes} min para proximo lote...")
                time.sleep(batch_interval_minutes * 60)
            finally:
                _release_lock(lock_path)

    except KeyboardInterrupt:
        _release_lock(lock_path)
        print(f"\n[PARADO] Micro-batch encerrado apos {ciclo} ciclos.")


def run_single_cycle(skip_load: bool = False):
    """Executa um unico ciclo do pipeline completo."""
    print("=" * 60)
    print(f"  BTG AlphaFeed v3.0 — Pipeline Completo")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print("  Etapas: Crawlers → Ingestao → Processamento → Resumo → Migracao → Notificacao → Cleanup")
    print()
    
    # Verificações iniciais
    if not check_env_file():
        return False
    
    # ETAPA 0: Verifica banco local
    if not check_and_start_local_db():
        print("[ERRO] Falha na verificacao do banco local")
        return False
    
    # PRE-STEP: Feedback Learning (atualiza regras antes do processamento)
    run_feedback_learning()

    # ETAPA 0.5: Crawlers (roda ANTES do load para gerar dump.json na pasta pdfs)
    if not skip_load:
        run_crawlers()

    # ETAPA 1: Carregamento de noticias (opcional - pode pular se nao tem PDFs novos)
    if not skip_load:
        if not run_load_news():
            print("[AVISO] Falha no carregamento de noticias (continuando...)")
    
    # ETAPA 2: Processamento de artigos (incremental: so pendentes)
    if not run_process_articles():
        print("[ERRO] Falha no processamento de artigos")
        return False
    
    # ETAPA 3: Resumo do dia (banco local — roda ANTES da migracao para liberar rapido)
    run_resumo_diario()

    # ETAPA 4: Migracao incremental (local → producao)
    if not run_migrate_incremental():
        print("[AVISO] Falha na migracao (continuando...)")
    
    # ETAPA 5: Notificacoes Telegram (individuais)
    run_notify()
    
    # ETAPA 6: Daily Briefing sintetizado
    run_telegram_briefing()

    # ETAPA 7: Limpeza de dados antigos (>90 dias — preserva resumos)
    run_cleanup(days=90)

    print(f"\n[OK] Ciclo concluido em {time.strftime('%H:%M:%S')}")
    return True


def run_scheduler(interval_minutes: int = 60, skip_load: bool = False):
    """
    Roda o pipeline em loop continuo a cada N minutos.
    Para com Ctrl+C.
    
    Args:
        interval_minutes: Intervalo entre execucoes em minutos. Default 60.
        skip_load: Se True, pula o carregamento de PDFs em cada ciclo.
    """
    print("=" * 60)
    print(f"BTG AlphaFeed - SCHEDULER (a cada {interval_minutes} min)")
    print(f"Inicio: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Skip load: {skip_load}")
    print("Pressione Ctrl+C para parar")
    print("=" * 60)
    
    ciclo = 0
    try:
        while True:
            ciclo += 1
            print(f"\n{'#'*60}")
            print(f"# CICLO {ciclo} - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#'*60}")
            
            start = time.time()
            
            try:
                ok = run_single_cycle(skip_load=skip_load)
                elapsed = time.time() - start
                status = "OK" if ok else "FALHA"
                print(f"\n[{status}] Ciclo {ciclo} concluido em {elapsed:.0f}s")
            except Exception as e:
                elapsed = time.time() - start
                print(f"\n[ERRO] Ciclo {ciclo} falhou apos {elapsed:.0f}s: {e}")
            
            # Aguarda proximo ciclo
            wait_seconds = interval_minutes * 60
            next_run = time.strftime('%H:%M:%S', time.localtime(time.time() + wait_seconds))
            print(f"\n⏰ Proximo ciclo em {interval_minutes} min (as {next_run})")
            print(f"   Pressione Ctrl+C para parar.\n")
            time.sleep(wait_seconds)
            
    except KeyboardInterrupt:
        print(f"\n\n[PARADO] Scheduler encerrado apos {ciclo} ciclos.")


def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(description="BTG AlphaFeed - Fluxo Completo Automatizado")
    parser.add_argument("--scheduler", action="store_true",
                        help="Roda em loop continuo (a cada N minutos)")
    parser.add_argument("--interval", type=int, default=60,
                        help="Intervalo entre ciclos em minutos (default: 60)")
    parser.add_argument("--skip-load", action="store_true",
                        help="Pula carregamento de PDFs (util em ciclos rapidos)")
    parser.add_argument("--single", action="store_true",
                        help="Executa um unico ciclo e sai (modo incremental)")
    parser.add_argument("--notify-only", action="store_true",
                        help="Apenas envia notificacoes pendentes")
    parser.add_argument("--microbatch", action="store_true",
                        help="Modo micro-batch: monitora pasta de PDFs e processa em lotes")
    parser.add_argument("--batch-interval", type=int, default=3,
                        help="Intervalo entre micro-lotes em minutos (default: 3)")
    args = parser.parse_args()
    
    # --microbatch: monitora pasta e processa em lotes
    if args.microbatch:
        if not check_conda_env():
            sys.exit(1)
        if not check_env_file():
            sys.exit(1)
        if not check_and_start_local_db():
            sys.exit(1)
        run_microbatch_cycle(batch_interval_minutes=args.batch_interval)
        return
    
    # --notify-only: so envia notificacoes
    if args.notify_only:
        check_env_file()
        run_notify()
        return
    
    # --scheduler: loop continuo
    if args.scheduler:
        if not check_conda_env():
            sys.exit(1)
        run_scheduler(interval_minutes=args.interval, skip_load=args.skip_load)
        return
    
    # --single: um ciclo e sai
    if args.single:
        if not check_conda_env():
            sys.exit(1)
        ok = run_single_cycle(skip_load=args.skip_load)
        sys.exit(0 if ok else 1)
    
    # Modo padrao: usa run_single_cycle (mesmo pipeline completo do --single)
    if not check_conda_env():
        sys.exit(1)
    ok = run_single_cycle(skip_load=False)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main() 