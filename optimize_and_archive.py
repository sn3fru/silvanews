#!/usr/bin/env python3
"""
Otimização e arquivamento de artigos antigos.

Objetivo
- Manter somente os últimos N dias na tabela principal `artigos_brutos`
  e mover o restante para `artigos_brutos_cold`.
- Criar índices úteis para o padrão de consultas do feed
  (por data, tipo_fonte e filtros do feed) sem alterar o código existente.

Características
- Seguro e idempotente (usa IF NOT EXISTS; processa em lotes)
- Não altera schema dos modelos existentes nem endpoints
- Pode operar em múltiplos bancos (local e produção) na mesma execução

Uso (exemplos)
  # Local (7 dias, lote 2000, dry-run)
  python optimize_and_archive.py --database postgresql+psycopg2://postgres_local@localhost:5433/devdb --days 7 --batch-size 2000 --dry-run

  # Executar de fato (local)
  python optimize_and_archive.py --database postgresql+psycopg2://postgres_local@localhost:5433/devdb --days 7 --batch-size 2000

  # Local e Produção (mesma operação nas duas)
  python optimize_and_archive.py \
    --database postgresql+psycopg2://postgres_local@localhost:5433/devdb \
    --also-database postgres://USER:PASS@HOST:5432/DBNAME \
    --days 7 --batch-size 2000
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, date
from typing import List

from sqlalchemy import create_engine, text


def normalize_db_url(url: str) -> str:
    if not url:
        raise ValueError("DATABASE URL vazio")
    url = url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def ensure_cold_table(engine) -> None:
    with engine.begin() as conn:
        # Cria tabela cold com a mesma estrutura (incluindo índices, defaults e constraints)
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS artigos_brutos_cold (LIKE artigos_brutos INCLUDING ALL);
            """
        ))

        # Índices auxiliares (evitar duplicidade de nomes em diferentes ambientes)
        conn.execute(text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname = ANY (current_schemas(false)) AND indexname = 'idx_artigos_cold_created_date'
                ) THEN
                    CREATE INDEX idx_artigos_cold_created_date ON artigos_brutos_cold (created_at);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname = ANY (current_schemas(false)) AND indexname = 'idx_artigos_cold_cluster_date'
                ) THEN
                    CREATE INDEX idx_artigos_cold_cluster_date ON artigos_brutos_cold (cluster_id, created_at);
                END IF;
            END $$;
            """
        ))


def create_optimization_indexes(engine) -> None:
    """Cria índices úteis para o padrão de consultas do feed (clusters por data/tipo)."""
    with engine.begin() as conn:
        # Index por expressão: date(created_at) para casar com "func.date(created_at) == target_date"
        conn.execute(text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname = ANY (current_schemas(false)) AND indexname = 'idx_clusters_created_date_expr'
                ) THEN
                    CREATE INDEX idx_clusters_created_date_expr ON clusters_eventos ((date(created_at)));
                END IF;
            END $$;
            """
        ))

        # Índice composto para o feed (parcial: somente exibíveis)
        conn.execute(text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname = ANY (current_schemas(false)) AND indexname = 'idx_clusters_feed_partial'
                ) THEN
                    CREATE INDEX idx_clusters_feed_partial
                    ON clusters_eventos (tipo_fonte, created_at DESC)
                    WHERE status = 'ativo' AND prioridade <> 'IRRELEVANTE' AND tag <> 'IRRELEVANTE';
                END IF;
            END $$;
            """
        ))

        # Para artigos, um índice por expressão de data também ajuda para tarefas de manutenção
        conn.execute(text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes WHERE schemaname = ANY (current_schemas(false)) AND indexname = 'idx_artigos_created_date_expr'
                ) THEN
                    CREATE INDEX idx_artigos_created_date_expr ON artigos_brutos ((date(created_at)));
                END IF;
            END $$;
            """
        ))


def move_old_articles(engine, days: int, batch_size: int, dry_run: bool, quiet: bool = False) -> None:
    cutoff_dt = datetime.utcnow() - timedelta(days=days)
    if not quiet:
        print(f"📦 Movendo artigos com created_at < {cutoff_dt.isoformat()} ... {'(dry-run)' if dry_run else ''}")

    ensure_cold_table(engine)

    moved_total = 0
    deleted_total = 0
    compacted_total = 0
    with engine.begin() as conn:
        # Conta candidatos
        total = conn.execute(text(
            "SELECT COUNT(*) FROM artigos_brutos WHERE created_at < :cutoff"
        ), {"cutoff": cutoff_dt}).scalar() or 0
    if not quiet:
        print(f"🔎 Candidatos a mover: {total}")

    if total == 0:
        if not quiet:
            print("✅ Nada a mover.")
        return

    if dry_run:
        batches = (total + batch_size - 1) // batch_size
        if not quiet:
            print(f"📝 Dry-run: {total} itens em {batches} lote(s) de até {batch_size}.")
        return

    while True:
        with engine.begin() as conn:
            ids = [row[0] for row in conn.execute(text(
                """
                SELECT id FROM artigos_brutos
                WHERE created_at < :cutoff
                ORDER BY id
                LIMIT :lim
                """
            ), {"cutoff": cutoff_dt, "lim": batch_size}).fetchall()]

            if not ids:
                break

            if not quiet:
                print(f"  ↪ Lote: {len(ids)} itens")

            # Move: insere no cold e depois remove do principal
            conn.execute(text(
                """
                INSERT INTO artigos_brutos_cold
                SELECT * FROM artigos_brutos WHERE id = ANY(:ids)
                """
            ), {"ids": ids})

            # Identifica IDs referenciados por FKs para evitar violação
            ref_rows = conn.execute(text(
                """
                SELECT a.id
                FROM artigos_brutos a
                WHERE a.id = ANY(:ids)
                  AND (
                        EXISTS (SELECT 1 FROM feedback_noticias f WHERE f.artigo_id = a.id)
                     OR EXISTS (SELECT 1 FROM logs_processamento l WHERE l.artigo_id = a.id)
                     OR EXISTS (SELECT 1 FROM semantic_embeddings s WHERE s.artigo_id = a.id)
                  )
                """
            ), {"ids": ids}).fetchall()
            referenced_ids = {r[0] for r in ref_rows}

            deletable_ids = [i for i in ids if i not in referenced_ids]
            if deletable_ids:
                conn.execute(text(
                    "DELETE FROM artigos_brutos WHERE id = ANY(:ids)"
                ), {"ids": deletable_ids})
                deleted_total += len(deletable_ids)

            # Para IDs referenciados, compacta (nulos nos campos pesados) sem deletar
            if referenced_ids:
                conn.execute(text(
                    """
                    UPDATE artigos_brutos
                    SET texto_bruto = '',
                        texto_processado = NULL,
                        embedding = NULL
                    WHERE id = ANY(:ids)
                      AND created_at < :cutoff
                    """
                ), {"ids": list(referenced_ids), "cutoff": cutoff_dt})
                compacted_total += len(referenced_ids)

            moved_total += len(ids)

    if not quiet:
        print(f"✅ Copiados para cold: {moved_total} | Removidos do principal: {deleted_total} | Compactados (referenciados): {compacted_total}")


def set_search_path(engine, schema: str) -> None:
    if not schema:
        return
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))


def optimize_database(db_urls: List[str], days: int, batch_size: int, dry_run: bool, schema: str | None, quiet: bool) -> None:
    for raw_url in db_urls:
        db_url = normalize_db_url(raw_url)
        if not quiet:
            print(f"\n🔧 Otimizando banco: {db_url}")
        engine = create_engine(db_url, pool_pre_ping=True)

        # Schema opcional
        if schema:
            set_search_path(engine, schema)

        # Índices para acelerar feed e contadores
        create_optimization_indexes(engine)

        # Arquivamento
        move_old_articles(engine, days=days, batch_size=batch_size, dry_run=dry_run, quiet=quiet)

        # VACUUM/ANALYZE são opcionais (normalmente feitos fora do app)
        if not quiet:
            print("ℹ️ Sugestão: executar VACUUM (FULL) ANALYZE em janelas de baixa carga para maior ganho.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Arquiva artigos antigos e cria índices de performance")
    p.add_argument("--database", required=True, help="URL do banco principal (local/produção)")
    p.add_argument("--also-database", action="append", default=[], help="URLs adicionais de bancos para aplicar as mesmas ações (pode repetir)")
    p.add_argument("--days", type=int, default=7, help="Manter somente os últimos N dias no principal (default: 7)")
    p.add_argument("--batch-size", type=int, default=2000, help="Tamanho do lote de movimentação (default: 2000)")
    p.add_argument("--dry-run", action="store_true", help="Apenas contabiliza, não move")
    p.add_argument("--schema", default=None, help="Schema alvo (opcional). Se definido, ajusta o search_path")
    p.add_argument("--quiet", action="store_true", help="Saída reduzida (não imprime por-lote)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dbs = [args.database] + list(args.also_database)
    optimize_database(dbs, days=args.days, batch_size=args.batch_size, dry_run=args.dry_run, schema=args.schema, quiet=args.quiet)
    if not args.quiet:
        print("\n🎯 Otimização concluída.")


if __name__ == "__main__":
    main()


