"""
Script para aplicar as tabelas do Graph-RAG no PostgreSQL de PRODUCAO (Heroku).

Executa:
  1. migrate_graph_tables  -> cria tabelas, extensoes e indices
  2. backfill_graph        -> popula o grafo com entidades dos artigos existentes

Uso:
    conda activate pymc2
    python scripts/apply_graph_heroku.py                       # migracao + backfill
    python scripts/apply_graph_heroku.py --migrate-only        # so cria tabelas
    python scripts/apply_graph_heroku.py --backfill-only       # so popula grafo
    python scripts/apply_graph_heroku.py --dry-run             # simula sem alterar
    python scripts/apply_graph_heroku.py --days 30 --limit 500 # backfill customizado
"""

import sys
import os
from pathlib import Path
import argparse

# ──────────────────────────────────────────────────────────────
# CONFIGURACAO DE PRODUCAO (Heroku)
# ──────────────────────────────────────────────────────────────
HEROKU_DATABASE_URL = (
    "postgres://u71uif3ajf4qqh:pbfa5924f245d80b107c9fb38d5496afc0c1372a3f163959faa933e5b9f7c47d6"
    "@c3v5n5ajfopshl.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/daoetg9ahbmcff"
)

# Diretórios
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def confirmar_producao() -> bool:
    """Pede confirmacao explicita antes de alterar producao."""
    print()
    print("!" * 60)
    print("  ATENCAO: Voce esta prestes a alterar o banco de PRODUCAO")
    print("  Host: ...rds.amazonaws.com (Heroku Postgres)")
    print("!" * 60)
    print()
    resp = input("Deseja continuar? (digite 'sim' para confirmar): ").strip().lower()
    return resp == "sim"


def set_producao_env():
    """Seta DATABASE_URL para producao (Heroku) no processo atual."""
    os.environ["DATABASE_URL"] = HEROKU_DATABASE_URL
    print("[ENV] DATABASE_URL setado para Heroku (producao)")


def run_migration() -> bool:
    """Executa a migracao de tabelas (migrate_graph_tables)."""
    print("\n" + "=" * 60)
    print("  ETAPA 1: MIGRACAO DE TABELAS (Graph-RAG)")
    print("=" * 60)

    try:
        # Forca reimport com a nova DATABASE_URL
        # Limpa modulos cacheados do backend para pegar a nova env
        mods_to_clear = [k for k in sys.modules if k.startswith("backend.")]
        for m in mods_to_clear:
            del sys.modules[m]

        from backend.database import engine, Base, GraphEntity, GraphEdge
        from sqlalchemy import text, inspect

        # 1. Cria tabelas via ORM
        print("\n[1/3] Criando tabelas via SQLAlchemy ORM...")
        Base.metadata.create_all(bind=engine)
        print("  OK - Tabelas criadas/verificadas")

        # 2. Extensoes e indices especiais
        print("\n[2/3] Extensoes e indices especiais...")
        with engine.connect() as conn:
            for ext in ["uuid-ossp", "pg_trgm"]:
                try:
                    conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
                    conn.commit()
                    print(f"  OK - Extensao {ext}")
                except Exception as e:
                    print(f"  AVISO - Extensao {ext}: {e}")
                    conn.rollback()

            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
                print("  OK - Extensao pgvector")
            except Exception as e:
                print(f"  AVISO - pgvector nao disponivel: {e}")
                conn.rollback()

            # Indice trigram
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_graph_entity_trgm
                    ON graph_entities USING gin (canonical_name gin_trgm_ops)
                """))
                conn.commit()
                print("  OK - Indice trigram")
            except Exception as e:
                print(f"  AVISO - Indice trigram: {e}")
                conn.rollback()

            # Coluna embedding_v2 (BYTEA - compativel com ORM e banco local)
            try:
                result = conn.execute(text("""
                    SELECT data_type, udt_name FROM information_schema.columns
                    WHERE table_name = 'artigos_brutos' AND column_name = 'embedding_v2'
                """))
                row = result.fetchone()
                if not row:
                    # Coluna nao existe: cria como BYTEA (mesmo tipo do ORM)
                    conn.execute(text(
                        "ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 BYTEA"
                    ))
                    conn.commit()
                    print("  OK - Coluna embedding_v2 criada (BYTEA)")
                else:
                    udt_name = (row[1] or "").lower()
                    if udt_name == "vector":
                        # Coluna existe como vector(768) - incompativel com ORM (LargeBinary=BYTEA)
                        # Dropar e recriar como BYTEA (dados serao re-gerados via backfill/migracao)
                        print(f"  AVISO - embedding_v2 e tipo 'vector'. Convertendo para BYTEA...")
                        conn.execute(text("ALTER TABLE artigos_brutos DROP COLUMN embedding_v2"))
                        conn.execute(text("ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 BYTEA"))
                        conn.commit()
                        print("  OK - embedding_v2 convertida: vector -> BYTEA")
                    else:
                        print(f"  OK - Coluna embedding_v2 ja existe (tipo: {udt_name})")
            except Exception as e:
                print(f"  AVISO - embedding_v2: {e}")
                conn.rollback()

            # Coluna metadados na tabela feedback_noticias (Feature 4A)
            try:
                result = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'feedback_noticias' AND column_name = 'metadados'
                """))
                if not result.fetchone():
                    conn.execute(text(
                        "ALTER TABLE feedback_noticias ADD COLUMN metadados JSONB DEFAULT '{}'::jsonb"
                    ))
                    conn.commit()
                    print("  OK - Coluna metadados em feedback_noticias")
                else:
                    print("  OK - Coluna metadados em feedback_noticias ja existe")
            except Exception as e:
                print(f"  AVISO - metadados feedback: {e}")
                conn.rollback()

            # Colunas de notificacao incremental na tabela clusters_eventos
            for col_name, col_def in [
                ("ja_notificado", "BOOLEAN DEFAULT FALSE NOT NULL"),
                ("notificado_em", "TIMESTAMP"),
            ]:
                try:
                    result = conn.execute(text(f"""
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'clusters_eventos' AND column_name = '{col_name}'
                    """))
                    if not result.fetchone():
                        conn.execute(text(
                            f"ALTER TABLE clusters_eventos ADD COLUMN {col_name} {col_def}"
                        ))
                        conn.commit()
                        print(f"  OK - Coluna {col_name} em clusters_eventos")
                    else:
                        print(f"  OK - Coluna {col_name} em clusters_eventos ja existe")
                except Exception as e:
                    print(f"  AVISO - {col_name}: {e}")
                    conn.rollback()

            # Indice para busca de clusters nao notificados
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_clusters_notificado
                    ON clusters_eventos(ja_notificado, created_at)
                """))
                conn.commit()
                print("  OK - Indice idx_clusters_notificado")
            except Exception as e:
                print(f"  AVISO - Indice notificado: {e}")
                conn.rollback()

            # Tabela prompt_configs (Feedback Learning System)
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS prompt_configs (
                        id SERIAL PRIMARY KEY,
                        chave VARCHAR(120) UNIQUE NOT NULL,
                        valor TEXT NOT NULL,
                        descricao TEXT,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_prompt_configs_chave
                    ON prompt_configs(chave)
                """))
                conn.commit()
                print("  OK - Tabela prompt_configs (Feedback Learning)")
            except Exception as e:
                print(f"  AVISO - prompt_configs: {e}")
                conn.rollback()

            # Procedure de arquivamento
            try:
                conn.execute(text("""
                    CREATE OR REPLACE FUNCTION archive_old_data(
                        days_to_keep INTEGER DEFAULT 90
                    )
                    RETURNS void AS $$
                    BEGIN
                        UPDATE artigos_brutos
                        SET status = 'arquivado'
                        WHERE created_at < NOW() - (days_to_keep || ' days')::interval
                          AND status NOT IN ('arquivado');
                        UPDATE clusters_eventos
                        SET status = 'arquivado'
                        WHERE created_at < NOW() - (days_to_keep || ' days')::interval
                          AND status NOT IN ('arquivado', 'descartado');
                    END;
                    $$ LANGUAGE plpgsql;
                """))
                conn.commit()
                print("  OK - Procedure archive_old_data()")
            except Exception as e:
                print(f"  AVISO - Procedure: {e}")
                conn.rollback()

        # 3. Verificacao
        print("\n[3/3] Verificando tabelas no Heroku...")
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        for t in ["graph_entities", "graph_edges"]:
            if t in tables:
                cols = [c["name"] for c in inspector.get_columns(t)]
                print(f"  OK - {t}: {', '.join(cols)}")
            else:
                print(f"  FALTA - {t}")

        # Verifica embedding_v2
        artigos_cols = [c["name"] for c in inspector.get_columns("artigos_brutos")]
        if "embedding_v2" in artigos_cols:
            print("  OK - artigos_brutos.embedding_v2 presente")
        else:
            print("  FALTA - artigos_brutos.embedding_v2")

        # Verifica metadados em feedback_noticias
        if "feedback_noticias" in tables:
            fb_cols = [c["name"] for c in inspector.get_columns("feedback_noticias")]
            if "metadados" in fb_cols:
                print("  OK - feedback_noticias.metadados presente")
            else:
                print("  FALTA - feedback_noticias.metadados")

        # Verifica colunas de notificacao em clusters_eventos
        if "clusters_eventos" in tables:
            ce_cols = [c["name"] for c in inspector.get_columns("clusters_eventos")]
            for col in ["ja_notificado", "notificado_em"]:
                if col in ce_cols:
                    print(f"  OK - clusters_eventos.{col} presente")
                else:
                    print(f"  FALTA - clusters_eventos.{col}")

        print("\n  MIGRACAO CONCLUIDA COM SUCESSO!")
        return True

    except Exception as e:
        print(f"\n  ERRO na migracao: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_backfill(days: int, limit: int, batch_size: int, dry_run: bool) -> bool:
    """Executa o backfill do grafo na producao."""
    print("\n" + "=" * 60)
    print("  ETAPA 2: BACKFILL DO GRAFO (Producao)")
    print("=" * 60)

    try:
        # Reimporta com a env de producao
        mods_to_clear = [k for k in sys.modules if k.startswith("backend.")]
        for m in mods_to_clear:
            del sys.modules[m]

        # Importa e executa o backfill (ele usa DATABASE_URL via backend.database)
        # Tenta import como modulo (scripts.backfill_graph) ou direto (backfill_graph)
        try:
            from scripts.backfill_graph import run_backfill as _run_backfill
        except ModuleNotFoundError:
            from backfill_graph import run_backfill as _run_backfill
        _run_backfill(days=days, limit=limit, batch_size=batch_size, dry_run=dry_run)
        return True

    except Exception as e:
        print(f"\n  ERRO no backfill: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Aplica Graph-RAG no PostgreSQL de Producao (Heroku)"
    )
    parser.add_argument(
        "--migrate-only", action="store_true",
        help="Executa apenas a migracao (cria tabelas)"
    )
    parser.add_argument(
        "--backfill-only", action="store_true",
        help="Executa apenas o backfill (popula grafo)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simula o backfill sem alterar dados"
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Ultimos N dias para backfill (default: 90)"
    )
    parser.add_argument(
        "--limit", type=int, default=5000,
        help="Maximo de artigos no backfill (default: 5000)"
    )
    parser.add_argument(
        "--batch", type=int, default=50,
        help="Tamanho do lote por chamada LLM (default: 50)"
    )
    parser.add_argument(
        "--skip-confirm", action="store_true",
        help="Pula confirmacao (usar com cuidado!)"
    )
    args = parser.parse_args()

    # Banner
    print("=" * 60)
    print("  GRAPH-RAG v2.0 -> HEROKU (PRODUCAO)")
    print("=" * 60)

    # Confirmacao de seguranca
    if not args.skip_confirm:
        if not confirmar_producao():
            print("\nOperacao cancelada pelo usuario.")
            sys.exit(0)

    # Seta DATABASE_URL para producao
    set_producao_env()

    # Adiciona diretorio do projeto ao path
    sys.path.insert(0, str(PROJECT_DIR))

    # Carrega .env para pegar GEMINI_API_KEY (sem sobrescrever DATABASE_URL)
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / "backend" / ".env", override=False)

    success = True

    # Etapa 1: Migracao
    if not args.backfill_only:
        ok = run_migration()
        if not ok:
            print("\n[ERRO] Migracao falhou. Abortando.")
            sys.exit(1)

    # Etapa 2: Backfill
    if not args.migrate_only:
        ok = run_backfill(
            days=args.days,
            limit=args.limit,
            batch_size=args.batch,
            dry_run=args.dry_run,
        )
        if not ok:
            success = False

    # Resultado final
    print("\n" + "=" * 60)
    if success:
        print("  TUDO CONCLUIDO COM SUCESSO NO HEROKU!")
    else:
        print("  CONCLUIDO COM AVISOS (verifique os logs acima)")
    print("=" * 60)


if __name__ == "__main__":
    main()
