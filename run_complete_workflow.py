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

def sync_prod_to_local():
    """
    ETAPA 0: Sincroniza dados multi-tenant de producao para o banco local.
    Traz usuarios, preferencias e templates que foram criados/alterados no frontend (producao).
    Isso garante que o pipeline local saiba das preferencias de cada usuario antes de gerar resumos.
    """
    try:
        print(f"\n{'=' * 60}")
        print("  ETAPA 0: SYNC PRODUCAO → LOCAL (usuarios/preferencias)")
        print(f"{'=' * 60}")

        LOCAL_DB = "postgresql+psycopg2://postgres_local@localhost:5433/devdb"
        PROD_DB = PRODUCTION_DATABASE_URL

        from sqlalchemy import create_engine, text as sa_text
        from sqlalchemy.orm import sessionmaker

        def _norm_url(url):
            u = url.strip().rstrip("| ")
            if u.startswith("postgres://"):
                return "postgresql+psycopg2://" + u[len("postgres://"):]
            if u.startswith("postgresql://") and not u.startswith("postgresql+psycopg2://"):
                return "postgresql+psycopg2://" + u[len("postgresql://"):]
            return u

        prod_engine = create_engine(_norm_url(PROD_DB), pool_pre_ping=True)
        local_engine = create_engine(_norm_url(LOCAL_DB), pool_pre_ping=True)

        from backend.database import Base, Usuario, PreferenciaUsuario, TemplateResumoUsuario
        Base.metadata.create_all(bind=local_engine)
        Base.metadata.create_all(bind=prod_engine)

        ProdSession = sessionmaker(bind=prod_engine)
        LocalSession = sessionmaker(bind=local_engine)
        db_prod = ProdSession()
        db_local = LocalSession()

        try:
            # --- Usuarios ---
            try:
                prod_users = db_prod.query(Usuario).all()
            except Exception as e:
                if "does not exist" in str(e):
                    db_prod.rollback()
                    print("  [INFO] Tabela 'usuarios' nao existe em producao. Nada a sincronizar.")
                    return True
                raise

            synced_users = 0
            user_id_map = {}
            for pu in prod_users:
                local_user = db_local.query(Usuario).filter(Usuario.email == pu.email).first()
                if local_user:
                    local_user.nome = pu.nome
                    local_user.ativo = pu.ativo
                    local_user.role = pu.role
                    user_id_map[pu.id] = local_user.id
                else:
                    new_u = Usuario(
                        nome=pu.nome, email=pu.email, senha_hash=pu.senha_hash,
                        ativo=pu.ativo, role=pu.role,
                    )
                    db_local.add(new_u)
                    db_local.flush()
                    user_id_map[pu.id] = new_u.id
                synced_users += 1
            db_local.commit()
            print(f"  [OK] Usuarios sincronizados: {synced_users}")

            # --- Preferencias ---
            try:
                prod_prefs = db_prod.query(PreferenciaUsuario).all()
            except Exception:
                db_prod.rollback()
                prod_prefs = []

            synced_prefs = 0
            for pp in prod_prefs:
                local_uid = user_id_map.get(pp.user_id)
                if not local_uid:
                    continue
                local_pref = db_local.query(PreferenciaUsuario).filter(
                    PreferenciaUsuario.user_id == local_uid
                ).first()
                if local_pref:
                    local_pref.tags_interesse = pp.tags_interesse
                    local_pref.tags_ignoradas = pp.tags_ignoradas
                    local_pref.tipo_fonte_preferido = pp.tipo_fonte_preferido
                    local_pref.tamanho_resumo = pp.tamanho_resumo
                    local_pref.config_extra = pp.config_extra
                else:
                    new_p = PreferenciaUsuario(
                        user_id=local_uid,
                        tags_interesse=pp.tags_interesse,
                        tags_ignoradas=pp.tags_ignoradas,
                        tipo_fonte_preferido=pp.tipo_fonte_preferido,
                        tamanho_resumo=pp.tamanho_resumo,
                        config_extra=pp.config_extra,
                    )
                    db_local.add(new_p)
                synced_prefs += 1
            db_local.commit()
            print(f"  [OK] Preferencias sincronizadas: {synced_prefs}")

            # --- Templates ---
            try:
                prod_templates = db_prod.query(TemplateResumoUsuario).all()
            except Exception:
                db_prod.rollback()
                prod_templates = []

            synced_tpl = 0
            for pt in prod_templates:
                local_uid = user_id_map.get(pt.user_id)
                if not local_uid:
                    continue
                local_tpl = db_local.query(TemplateResumoUsuario).filter(
                    TemplateResumoUsuario.user_id == local_uid,
                    TemplateResumoUsuario.nome == pt.nome,
                ).first()
                if local_tpl:
                    local_tpl.descricao = pt.descricao
                    local_tpl.config = pt.config
                    local_tpl.ativo = pt.ativo
                else:
                    new_t = TemplateResumoUsuario(
                        user_id=local_uid, nome=pt.nome, descricao=pt.descricao,
                        config=pt.config, ativo=pt.ativo,
                    )
                    db_local.add(new_t)
                synced_tpl += 1
            db_local.commit()
            print(f"  [OK] Templates sincronizados: {synced_tpl}")

        finally:
            db_prod.close()
            db_local.close()

        print("  [OK] Sync producao → local concluido.")
        return True

    except Exception as e:
        print(f"  [AVISO] Sync producao → local falhou: {e}")
        return True


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
                parts = []
                if stats['artigos_deleted']:
                    parts.append(f"{stats['artigos_deleted']} artigos")
                if stats['clusters_deleted']:
                    parts.append(f"{stats['clusters_deleted']} clusters")
                if stats['chat_deleted']:
                    parts.append(f"{stats['chat_deleted']} chats")
                if stats.get('deps_deleted', 0):
                    parts.append(f"{stats['deps_deleted']} dependencias (feedbacks, grafos, sinteses)")
                print(f"[CLEANUP] Removidos: {', '.join(parts)}.")
            else:
                print("[CLEANUP] Nenhum dado antigo para remover.")
        finally:
            db.close()
    except Exception as e:
        import traceback
        print(f"[CLEANUP] Erro: {e}")
        traceback.print_exc()


def run_notify():
    """Envia notificacoes Telegram de clusters pendentes (individuais)."""
    try:
        env = _subprocess_env()
        if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
            return True

        print("\n  Enviando notificacoes individuais Telegram...")
        result = subprocess.run([
            sys.executable, "scripts/notify_telegram.py", "--limit", "50"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)

        if result.returncode == 0:
            print("  [OK] Notificacoes enviadas.")
        else:
            print("  [AVISO] Falha nas notificacoes (nao critico).")
        return True
            
    except Exception as e:
        print(f"[AVISO] Erro ao enviar notificacoes: {e}")
        return True  # Nao bloqueia pipeline


def run_telegram_briefing():
    """
    ETAPA 6: Envia Daily Briefing via Telegram (se configurado).
    O conteudo do briefing ja foi gerado e printado pelo run_resumo_diario().
    Esta etapa so faz o envio via bot do Telegram.
    """
    try:
        env = _subprocess_env()
        if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHAT_ID"):
            return True

        print("\n  Enviando briefing via Telegram...")
        result = subprocess.run([
            sys.executable, "send_telegram.py"
        ], cwd=Path(__file__).parent, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)

        if result.returncode == 0:
            print("  [OK] Briefing enviado ao Telegram.")
        else:
            print("  [AVISO] Falha ao enviar briefing (nao critico).")
        return True

    except Exception as e:
        print(f"  [AVISO] Telegram: {e}")
        return True


def _ensure_env_loaded():
    """Garante que as variaveis do backend/.env estao no os.environ (para chamadas in-process)."""
    if os.environ.get("GEMINI_API_KEY"):
        return
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / "backend" / ".env"
        if env_path.exists():
            load_dotenv(str(env_path), override=False)
    except ImportError:
        env = _subprocess_env()
        for key in ("GEMINI_API_KEY", "DATABASE_URL", "JWT_SECRET", "TIVALY_API_KEY"):
            if env.get(key) and not os.environ.get(key):
                os.environ[key] = env[key]


def run_resumo_diario():
    """
    Gera o resumo do dia em 2 fases:
    1. Resumo DEFAULT (compartilhado) — 1 chamada LLM, salvo com user_id=None.
       Todos os usuarios sem preferencias customizadas veem este resumo.
    2. Resumos PER-USER — apenas para usuarios com preferencias diferentes do default.
    Nao bloqueia o pipeline em caso de falha.
    """
    try:
        _ensure_env_loaded()

        print(f"\n{'=' * 60}")
        print("  ETAPA 3: RESUMO DO DIA")
        print(f"{'=' * 60}")

        from agents.resumo_diario.agent import gerar_resumo_diario, gerar_resumo_para_usuario, formatar_whatsapp, promover_clusters_pos_resumo
        from backend.utils import get_date_brasil

        target_date = get_date_brasil()
        print(f"  Data: {target_date.isoformat()}")

        # Acumula cluster_ids de todos os resumos para boost pós-resumo
        todos_ids_resumos: set = set()

        # --- Fase 1: Resumo DEFAULT (salvo com user_id=None) ---
        resultado = gerar_resumo_diario(target_date=target_date)

        if not resultado.get("ok"):
            err = resultado.get("error", "desconhecido")
            print(f"  [AVISO] Resumo default falhou: {err}")
        else:
            mensagens = formatar_whatsapp(resultado)
            print()
            for msg in mensagens:
                print(msg)
                print()
            ids_default = resultado.get("todos_clusters_escolhidos_ids", [])
            todos_ids_resumos.update(ids_default)
            total = len(ids_default)
            avaliados = len(resultado.get("clusters_avaliados_ids", []))
            print(f"  [OK] Resumo default: {total} clusters de {avaliados} avaliados.")

            # Salva como resumo default (user_id=None)
            try:
                from backend.database import SessionLocal
                from backend.crud import create_resumo_usuario
                db_default = SessionLocal()
                try:
                    texto_full = "\n\n---\n\n".join(mensagens) if mensagens else None
                    create_resumo_usuario(
                        db_default, None, target_date, template_id=None,
                        clusters_avaliados=resultado.get("clusters_avaliados_ids", []),
                        clusters_escolhidos=resultado.get("todos_clusters_escolhidos_ids", []),
                        texto=texto_full, texto_whatsapp=texto_full,
                        prompt_version=resultado.get("prompt_version", "DEFAULT_UNIFICADO"),
                        metadados=resultado.get("contract_dict", {}),
                    )
                    print(f"  [OK] Resumo default salvo no banco (user_id=NULL)")
                finally:
                    db_default.close()
            except Exception as e:
                print(f"  [AVISO] Falha ao salvar resumo default: {e}")

        # --- Fase 2: Resumos per-user (APENAS para quem tem prefs customizadas) ---
        try:
            from backend.database import SessionLocal
            from backend.crud import list_usuarios, create_resumo_usuario, get_preferencias_usuario, user_has_custom_prefs
            db = SessionLocal()
            try:
                usuarios = list_usuarios(db, apenas_ativos=True)
            except Exception:
                usuarios = []

            custom_users = []
            for user in usuarios:
                try:
                    prefs = get_preferencias_usuario(db, user.id)
                    if user_has_custom_prefs(prefs):
                        custom_users.append((user, prefs))
                except Exception:
                    pass
            db.close()

            if custom_users:
                print(f"\n  Gerando resumos personalizados para {len(custom_users)} usuario(s) com preferencias customizadas...")
                for user, prefs in custom_users:
                    try:
                        perfil = (prefs.config_extra or {}).get("perfil", "")

                        if perfil == "barretti":
                            from agents.resumo_diario.agent import gerar_resumo_barretti, formatar_barretti
                            res_user = gerar_resumo_barretti(target_date=target_date)
                            if res_user.get("ok"):
                                texto_full = formatar_barretti(res_user)
                                print(f"\n{'=' * 60}")
                                print(f"  RESUMO DO DIA — BARRETTI (Capital Solutions)")
                                print(f"{'=' * 60}")
                                print(texto_full)
                                print()
                                db2 = SessionLocal()
                                try:
                                    create_resumo_usuario(
                                        db2, user.id, target_date, template_id=None,
                                        clusters_avaliados=res_user.get("clusters_avaliados_ids", []),
                                        clusters_escolhidos=res_user.get("todos_clusters_escolhidos_ids", []),
                                        texto=texto_full, texto_whatsapp=texto_full,
                                        prompt_version=res_user.get("prompt_version"),
                                        metadados=res_user.get("contract_dict", {}),
                                    )
                                finally:
                                    db2.close()
                                ids_barretti = res_user.get("todos_clusters_escolhidos_ids", [])
                                todos_ids_resumos.update(ids_barretti)
                                n = len(ids_barretti)
                                print(f"    [OK] {user.nome or user.email} (barretti): {n} noticias salvas")
                            else:
                                print(f"    [AVISO] {user.nome or user.email} (barretti): {res_user.get('error', '?')}")
                        else:
                            res_user = gerar_resumo_para_usuario(user_id=user.id, target_date=target_date)
                            if res_user.get("ok"):
                                texto_wpp = formatar_whatsapp(res_user)
                                texto_full = "\n\n---\n\n".join(texto_wpp) if texto_wpp else None
                                print(f"\n{'=' * 60}")
                                print(f"  RESUMO DO DIA — {user.nome or user.email}")
                                print(f"{'=' * 60}")
                                for msg in (texto_wpp or []):
                                    print(msg)
                                    print()
                                db2 = SessionLocal()
                                try:
                                    create_resumo_usuario(
                                        db2, user.id, target_date, template_id=None,
                                        clusters_avaliados=res_user.get("clusters_avaliados_ids", []),
                                        clusters_escolhidos=res_user.get("todos_clusters_escolhidos_ids", []),
                                        texto=texto_full, texto_whatsapp=texto_full,
                                        prompt_version=res_user.get("prompt_version"),
                                        metadados=res_user.get("contract_dict", {}),
                                    )
                                finally:
                                    db2.close()
                                ids_user = res_user.get("todos_clusters_escolhidos_ids", [])
                                todos_ids_resumos.update(ids_user)
                                n = len(ids_user)
                                print(f"    [OK] {user.nome or user.email}: {n} itens salvos")
                            else:
                                print(f"    [AVISO] {user.nome or user.email}: {res_user.get('error', '?')}")
                    except Exception as e:
                        print(f"    [ERRO] {user.nome or user.email}: {e}")
            else:
                n_total = len(usuarios)
                print(f"  [OK] {n_total} usuario(s) ativo(s), todos usam resumo default (0 chamadas LLM extras).")
        except Exception as e:
            print(f"  [AVISO] Fase per-user falhou: {e}")

        # --- Fase 3: Boost de prioridade para clusters selecionados ---
        if todos_ids_resumos:
            print(f"\n  --- Fase 3: Boost de prioridade (P3→P2) ---")
            print(f"  {len(todos_ids_resumos)} cluster(s) selecionados em resumos.")
            try:
                boost_result = promover_clusters_pos_resumo(target_date, todos_ids_resumos)
                print(f"  [OK] Boost: {boost_result['promovidos']} promovidos, "
                      f"{boost_result['ja_p1_p2']} já P1/P2, "
                      f"{boost_result['nao_encontrados']} não encontrados.")
            except Exception as e:
                print(f"  [AVISO] Boost falhou: {e}")
        else:
            print(f"\n  [INFO] Nenhum cluster selecionado em resumos — boost dispensado.")

        return True

    except Exception as e:
        print(f"  [AVISO] Erro ao gerar resumo: {e}")
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

    # Garante que TODAS as tabelas do ORM existem no banco local
    # (incluindo multi-tenant: usuarios, preferencias, templates, resumos)
    try:
        _ensure_env_loaded()
        from backend.database import init_database
        init_database()
    except Exception as e:
        print(f"  [AVISO] init_database falhou: {e}")

    # ETAPA 0: Sync producao → local (usuarios, preferencias, templates)
    sync_prod_to_local()

    # PRE-STEP: Feedback Learning (atualiza regras antes do processamento)
    run_feedback_learning()

    # # ETAPA 0.5: Crawlers (roda ANTES do load para gerar dump.json na pasta pdfs)
    if not skip_load:
        # Só roda de segunda a sexta (0=segunda, 4=sexta)
        if time.localtime().tm_wday < 5:
            run_crawlers()
        else:
            print("[CRAWLERS] Fim de semana detectado. Pulando crawlers (etapa 0.5).")

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