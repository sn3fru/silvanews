"""
Script de migracao para criar as tabelas do Graph-RAG (v2.0).
Cria graph_entities e graph_edges sem alterar tabelas existentes.

Uso:
    conda activate pymc2
    python scripts/migrate_graph_tables.py
"""

import sys
import os

# Adiciona o diretorio pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import engine, Base, GraphEntity, GraphEdge


RAW_SQL_MIGRATION = """
-- =============================================
-- MIGRACAO v2.0: Graph-RAG Tables
-- Execute no Postgres (local ou Heroku)
-- =============================================

-- Habilita extensao de UUID (se nao existir)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Habilita extensao de vetores (pgvector) - necessario para RAG
-- NOTA: No Heroku, pode ser necessario habilitar via dashboard
CREATE EXTENSION IF NOT EXISTS vector;

-- Habilita extensao de trigram para Entity Resolution por texto
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Tabela de Entidades (Nos do Grafo)
CREATE TABLE IF NOT EXISTS graph_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type VARCHAR(50) NOT NULL,  -- PERSON, ORG, GOV, EVENT, CONCEPT
    description TEXT,
    aliases JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Indices da tabela de entidades
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_entity_canonical
    ON graph_entities(canonical_name, entity_type);
CREATE INDEX IF NOT EXISTS idx_graph_entity_type
    ON graph_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_graph_entity_name
    ON graph_entities(name);
-- Indice trigram para busca fuzzy de entidades
CREATE INDEX IF NOT EXISTS idx_graph_entity_trgm
    ON graph_entities USING gin (canonical_name gin_trgm_ops);

-- Tabela de Arestas (Conexoes Artigo <-> Entidade)
CREATE TABLE IF NOT EXISTS graph_edges (
    id SERIAL PRIMARY KEY,
    artigo_id INTEGER NOT NULL REFERENCES artigos_brutos(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
    relation_type VARCHAR(50) NOT NULL DEFAULT 'MENTIONED',
    sentiment_score FLOAT,
    context_snippet TEXT,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Indices da tabela de arestas
CREATE INDEX IF NOT EXISTS idx_graph_edge_artigo ON graph_edges(artigo_id);
CREATE INDEX IF NOT EXISTS idx_graph_edge_entity ON graph_edges(entity_id);
CREATE INDEX IF NOT EXISTS idx_graph_edge_relation ON graph_edges(relation_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_edge_artigo_entity
    ON graph_edges(artigo_id, entity_id);

-- Adicionar coluna de embedding vetorial (768d) na tabela de artigos existente
-- Usa pgvector se disponivel
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'artigos_brutos' AND column_name = 'embedding_v2'
    ) THEN
        -- Tenta com pgvector (tipo vector)
        BEGIN
            ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 vector(768);
            CREATE INDEX idx_artigos_embedding_v2_hnsw
                ON artigos_brutos USING hnsw (embedding_v2 vector_cosine_ops);
            RAISE NOTICE 'Coluna embedding_v2 criada com pgvector + HNSW index';
        EXCEPTION WHEN undefined_object THEN
            -- Fallback: usa BYTEA se pgvector nao disponivel
            ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 BYTEA;
            RAISE NOTICE 'Coluna embedding_v2 criada como BYTEA (pgvector nao disponivel)';
        END;
    ELSE
        RAISE NOTICE 'Coluna embedding_v2 ja existe';
    END IF;
END $$;

-- Procedure de janela movel: arquiva dados > 90 dias
-- (Mantem entidades e conexoes; arquiva artigos brutos)
CREATE OR REPLACE FUNCTION archive_old_data(days_to_keep INTEGER DEFAULT 90)
RETURNS void AS $$
BEGIN
    -- Soft delete de artigos antigos (mantem o grafo)
    UPDATE artigos_brutos
    SET status = 'arquivado'
    WHERE created_at < NOW() - (days_to_keep || ' days')::interval
      AND status NOT IN ('arquivado');

    -- Arquiva clusters antigos
    UPDATE clusters_eventos
    SET status = 'arquivado'
    WHERE created_at < NOW() - (days_to_keep || ' days')::interval
      AND status NOT IN ('arquivado', 'descartado');

    RAISE NOTICE 'Dados > % dias arquivados', days_to_keep;
END;
$$ LANGUAGE plpgsql;

SELECT 'Migracao v2.0 concluida com sucesso!' AS resultado;
"""


def run_migration():
    """Executa a migracao via SQLAlchemy (cria tabelas ORM)."""
    print("=" * 60)
    print("MIGRACAO v2.0: Graph-RAG Tables")
    print("=" * 60)

    # 1. Cria tabelas via SQLAlchemy ORM
    print("\n[1/3] Criando tabelas via SQLAlchemy ORM...")
    try:
        Base.metadata.create_all(bind=engine)
        print("  OK - Tabelas criadas/verificadas")
    except Exception as e:
        print(f"  ERRO ao criar tabelas ORM: {e}")
        return False

    # 2. Executa SQL raw para extensoes e indices especiais
    print("\n[2/3] Executando SQL raw (extensoes, indices, procedures)...")
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            # Extensoes individuais (podem falhar individualmente)
            for ext in ["uuid-ossp", "pg_trgm"]:
                try:
                    conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
                    conn.commit()
                    print(f"  OK - Extensao {ext}")
                except Exception as e:
                    print(f"  AVISO - Extensao {ext}: {e}")
                    conn.rollback()

            # pgvector (pode nao estar disponivel)
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
                print("  OK - Extensao pgvector")
            except Exception as e:
                print(f"  AVISO - pgvector nao disponivel: {e}")
                conn.rollback()

            # Indice trigram para entity resolution fuzzy
            try:
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_graph_entity_trgm
                    ON graph_entities USING gin (canonical_name gin_trgm_ops)
                """))
                conn.commit()
                print("  OK - Indice trigram para entity resolution")
            except Exception as e:
                print(f"  AVISO - Indice trigram: {e}")
                conn.rollback()

            # Coluna embedding_v2 na artigos_brutos
            try:
                result = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'artigos_brutos' AND column_name = 'embedding_v2'
                """))
                if not result.fetchone():
                    try:
                        conn.execute(text("ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 vector(768)"))
                        conn.execute(text("""
                            CREATE INDEX IF NOT EXISTS idx_artigos_embedding_v2_hnsw
                            ON artigos_brutos USING hnsw (embedding_v2 vector_cosine_ops)
                        """))
                        conn.commit()
                        print("  OK - Coluna embedding_v2 (pgvector 768d + HNSW)")
                    except Exception:
                        conn.rollback()
                        conn.execute(text("ALTER TABLE artigos_brutos ADD COLUMN embedding_v2 BYTEA"))
                        conn.commit()
                        print("  OK - Coluna embedding_v2 (BYTEA fallback)")
                else:
                    print("  OK - Coluna embedding_v2 ja existe")
            except Exception as e:
                print(f"  AVISO - embedding_v2: {e}")
                conn.rollback()

            # Procedure de arquivamento
            try:
                conn.execute(text("""
                    CREATE OR REPLACE FUNCTION archive_old_data(days_to_keep INTEGER DEFAULT 90)
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

            # Coluna metadados na tabela feedback_noticias (Feature 4A)
            try:
                result = conn.execute(text("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'feedback_noticias' AND column_name = 'metadados'
                """))
                if not result.fetchone():
                    conn.execute(text("ALTER TABLE feedback_noticias ADD COLUMN metadados JSONB DEFAULT '{}'::jsonb"))
                    conn.commit()
                    print("  OK - Coluna metadados em feedback_noticias")
                else:
                    print("  OK - Coluna metadados em feedback_noticias ja existe")
            except Exception as e:
                print(f"  AVISO - metadados feedback: {e}")
                conn.rollback()

            # Colunas de notificacao incremental em clusters_eventos
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

            # Indice para notificacoes pendentes
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

    except Exception as e:
        print(f"  ERRO geral no SQL raw: {e}")

    # 3. Verificacao final
    print("\n[3/3] Verificando tabelas criadas...")
    from sqlalchemy import inspect
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        for t in ["graph_entities", "graph_edges"]:
            if t in tables:
                cols = [c["name"] for c in inspector.get_columns(t)]
                print(f"  OK - {t}: {', '.join(cols)}")
            else:
                print(f"  FALTA - {t}")
    except Exception as e:
        print(f"  ERRO na verificacao: {e}")

    print("\n" + "=" * 60)
    print("MIGRACAO CONCLUIDA")
    print("=" * 60)
    print("\nSQL completo para Heroku (copie e cole no psql):")
    print("-" * 60)
    print(RAW_SQL_MIGRATION)
    return True


if __name__ == "__main__":
    run_migration()
