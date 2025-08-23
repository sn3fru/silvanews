#!/usr/bin/env python3
"""
Script de migração para adicionar a coluna tipo_fonte nas tabelas
artigos_brutos e clusters_eventos (local ou produção/Heroku).

Uso:
  # Local (usa DATABASE_URL do backend/database.py)
  python add_tipo_fonte_migration.py --yes

  # Produção (Heroku Postgres)
  python add_tipo_fonte_migration.py --url "postgres://..." --sslmode require --yes
"""

import os
import sys
import argparse
from urllib.parse import urlparse
from pathlib import Path
from sqlalchemy import text, create_engine

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

def _normalize_sqlalchemy_url(raw_url: str, sslmode: str | None = None) -> str:
    """Normaliza URL para SQLAlchemy/psycopg2 e adiciona sslmode se necessário."""
    if not raw_url:
        return raw_url
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]

    if sslmode:
        # Anexa sslmode se não existir
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}sslmode={sslmode}"
    return url

def _build_engine(cli_url: str | None, sslmode: str | None):
    if cli_url:
        norm = _normalize_sqlalchemy_url(cli_url, sslmode=sslmode)
        print(f"🔗 Usando URL explícita (destino): {urlparse(norm).hostname}:{urlparse(norm).port}")
        return create_engine(norm, pool_pre_ping=True)

    # Fallback para engine padrão do projeto (usa DATABASE_URL do ambiente)
    from backend.database import engine as default_engine, SQLALCHEMY_DATABASE_URI
    if sslmode and "sslmode=" not in SQLALCHEMY_DATABASE_URI:
        norm = _normalize_sqlalchemy_url(SQLALCHEMY_DATABASE_URI, sslmode=sslmode)
        print(f"🔗 Usando URL do ambiente com sslmode={sslmode}: {urlparse(norm).hostname}:{urlparse(norm).port}")
        return create_engine(norm, pool_pre_ping=True)
    print("🔗 Usando engine padrão do projeto (DATABASE_URL)")
    return default_engine

def run_migration(url: str | None = None, sslmode: str | None = None, assume_yes: bool = False, dry_run: bool = False):
    """Executa a migração para adicionar tipo_fonte."""
    engine = _build_engine(url, sslmode)

    target = urlparse(str(engine.url))
    print(f"🔄 Iniciando migração em: host={target.hostname} db={target.path.lstrip('/')}")
    if not assume_yes:
        try:
            resp = input("Confirmar execução? (digite 'SIM' para continuar): ").strip().upper()
        except EOFError:
            resp = ""
        if resp != "SIM":
            print("❌ Operação cancelada.")
            return

    if dry_run:
        print("ℹ️ DRY-RUN habilitado: nada será alterado.")

    with engine.begin() as conn:
        try:
            if not dry_run:
                # Adiciona coluna tipo_fonte na tabela artigos_brutos
                print("📊 Adicionando coluna tipo_fonte em artigos_brutos...")
                conn.execute(text(
                    """
                    ALTER TABLE artigos_brutos 
                    ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
                    """
                ))
                print("✅ Coluna tipo_fonte adicionada em artigos_brutos")

                # Adiciona coluna tipo_fonte na tabela clusters_eventos
                print("📊 Adicionando coluna tipo_fonte em clusters_eventos...")
                conn.execute(text(
                    """
                    ALTER TABLE clusters_eventos 
                    ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
                    """
                ))
                print("✅ Coluna tipo_fonte adicionada em clusters_eventos")

                # Cria índice para performance
                print("📊 Criando índices...")
                conn.execute(text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_artigos_tipo_fonte 
                    ON artigos_brutos(tipo_fonte);
                    """
                ))
                conn.execute(text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_clusters_tipo_fonte 
                    ON clusters_eventos(tipo_fonte);
                    """
                ))
                print("✅ Índices criados com sucesso")

                # Ajustes nas tabelas de prompts (tags/prioridades) para suportar internacional
                print("📊 Ajustando tabelas de prompts (tags/prioridades) para tipo_fonte...")
                conn.execute(text(
                    """
                    ALTER TABLE prompt_tags 
                    ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
                    """
                ))
                conn.execute(text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_prompt_tags_tipo_fonte ON prompt_tags(tipo_fonte);
                    """
                ))
                conn.execute(text(
                    """
                    ALTER TABLE prompt_prioridade_itens 
                    ADD COLUMN IF NOT EXISTS tipo_fonte VARCHAR(20) DEFAULT 'nacional' NOT NULL;
                    """
                ))
                conn.execute(text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_prompt_prioridade_tipo_fonte ON prompt_prioridade_itens(tipo_fonte);
                    """
                ))

            print("\n🎉 Migração concluída com sucesso!")

        except Exception as e:
            print(f"\n❌ Erro durante a migração: {e}")
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migração: adicionar tipo_fonte (local/heroku)")
    parser.add_argument("--url", help="DATABASE_URL de destino (ex.: postgres://user:pass@host:5432/db)")
    parser.add_argument("--sslmode", choices=["require", "prefer", "disable"], help="Forçar sslmode na conexão")
    parser.add_argument("--yes", action="store_true", help="Não perguntar confirmação")
    parser.add_argument("--dry-run", action="store_true", help="Executa sem aplicar alterações")
    args = parser.parse_args()

    run_migration(url=args.url, sslmode=args.sslmode, assume_yes=args.yes, dry_run=args.dry_run)
