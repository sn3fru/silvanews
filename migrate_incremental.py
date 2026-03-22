"""
Migração incremental e idempotente do Postgres local para o Postgres do Heroku.

Características:
- Incremental por timestamp (lê apenas registros novos/alterados desde a última execução)
- Idempotente em todas as entidades: Clusters, Artigos, Sínteses, Configurações,
  Alterações de Cluster, Chat (sessões e mensagens) e Logs
- Deduplicação para logs/alterações/mensagens de chat via chaves de negócio
- Batching para evitar consumo excessivo de memória

Uso típico:
  conda activate pymc2
  python -m btg_alphafeed.migrate_incremental \
    --source postgresql+psycopg2://postgres_local@localhost:5433/devdb \
    --dest   postgres://<usuario>:<senha>@<host>:5432/<db> \
    --include-logs --include-chat

Opções úteis:
  --meta-file <path>        Caminho do arquivo que armazena o último timestamp migrado
  --since <ISO-UTC>         Executa incremental a partir de um timestamp específico
  --no-update-existing      Não atualiza registros existentes (apenas insere os novos)
  --only <lista>            Migra apenas entidades específicas (ex: clusters,artigos,logs)
"""

from __future__ import annotations

import os
import sys
import argparse
import hashlib
from typing import Dict, Optional, Tuple, List, Iterable, Set
from datetime import datetime, timezone, timedelta, date as date_type

from sqlalchemy import create_engine, func, and_, or_, text
from sqlalchemy.orm import sessionmaker, Session, load_only

try:
    # Execução como módulo
    from .backend.database import (
        Base,
        ArtigoBruto,
        ClusterEvento,
        SinteseExecutiva,
        LogProcessamento,
        ConfiguracaoColeta,
        ChatSession,
        ChatMessage,
        ClusterAlteracao,
        PromptTag,
        PromptPrioridadeItem,
        PromptTemplate,
        FeedbackNoticia,
        EstagiarioChatSession,
        EstagiarioChatMessage,
        GraphEntity,
        GraphEdge,
        DeepResearchJob,
        SocialResearchJob,
        Usuario,
        PreferenciaUsuario,
        TemplateResumoUsuario,
        ResumoUsuario,
    )
except Exception:
    # Execução direta
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from backend.database import (  # type: ignore
        Base,
        ArtigoBruto,
        ClusterEvento,
        SinteseExecutiva,
        LogProcessamento,
        ConfiguracaoColeta,
        ChatSession,
        ChatMessage,
        ClusterAlteracao,
        PromptTag,
        PromptPrioridadeItem,
        PromptTemplate,
        FeedbackNoticia,
        EstagiarioChatSession,
        EstagiarioChatMessage,
        GraphEntity,
        GraphEdge,
        DeepResearchJob,
        SocialResearchJob,
        Usuario,
        PreferenciaUsuario,
        TemplateResumoUsuario,
        ResumoUsuario,
    )


# ==============================================================================
# Utilitários gerais
# ==============================================================================


def normalize_db_url(url: str) -> str:
    if not url:
        raise ValueError("DATABASE URL vazio")
    url = url.strip().rstrip("| ")
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def _ensure_new_columns(engine) -> None:
    """
    Garante que colunas adicionadas ao ORM existam na tabela fisica.
    ALTER TABLE ... ADD COLUMN IF NOT EXISTS e idempotente.
    Roda em AMBOS os bancos (source e dest) para evitar falha no SELECT.
    Tambem corrige incompatibilidade de tipo embedding_v2 (vector vs BYTEA).
    """
    _new_columns = [
        # (tabela, coluna, definicao SQL)
        ("clusters_eventos", "ja_notificado", "BOOLEAN DEFAULT FALSE NOT NULL"),
        ("clusters_eventos", "notificado_em", "TIMESTAMP"),
    ]
    try:
        with engine.connect() as conn:
            for table, col, col_def in _new_columns:
                try:
                    result = conn.execute(text(
                        f"SELECT 1 FROM information_schema.columns "
                        f"WHERE table_name = '{table}' AND column_name = '{col}'"
                    ))
                    if not result.fetchone():
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                        conn.commit()
                        print(f"  [Migration] Coluna {table}.{col} criada")
                    else:
                        pass  # ja existe, silencioso
                except Exception as e:
                    print(f"  [Migration] Aviso ao criar {table}.{col}: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            # Fix: converter embedding_v2 de vector(768) para BYTEA se necessario
            # (ORM define como LargeBinary=BYTEA, mas apply_graph_heroku pode ter criado como vector)
            try:
                result = conn.execute(text("""
                    SELECT data_type, udt_name FROM information_schema.columns
                    WHERE table_name = 'artigos_brutos' AND column_name = 'embedding_v2'
                """))
                row = result.fetchone()
                if row:
                    data_type = row[0] if row[0] else ""
                    udt_name = row[1] if row[1] else ""
                    if udt_name == "vector" or "vector" in data_type.lower():
                        print(f"  [Migration] embedding_v2 e tipo '{udt_name}' -> convertendo para BYTEA...")
                        conn.execute(text(
                            "ALTER TABLE artigos_brutos ALTER COLUMN embedding_v2 TYPE BYTEA USING embedding_v2::text::bytea"
                        ))
                        conn.commit()
                        print(f"  [Migration] embedding_v2 convertida para BYTEA com sucesso")
            except Exception as e:
                print(f"  [Migration] Aviso embedding_v2 type fix: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    except Exception as e:
        print(f"  [Migration] Aviso geral _ensure_new_columns: {e}")


def create_sessions(source_url: str, dest_url: str) -> Tuple[Session, Session]:
    source_engine = create_engine(normalize_db_url(source_url), pool_pre_ping=True)
    dest_engine = create_engine(normalize_db_url(dest_url), pool_pre_ping=True)

    # Garante que colunas novas do ORM existam em AMBOS os bancos
    print("🔧 Verificando schema (novas colunas)...")
    _ensure_new_columns(source_engine)
    _ensure_new_columns(dest_engine)

    # Cria tabelas que faltam em AMBOS os bancos (ex: tabelas multi-tenant v3.0)
    Base.metadata.create_all(bind=source_engine)
    Base.metadata.create_all(bind=dest_engine)

    SourceSession = sessionmaker(bind=source_engine, autocommit=False, autoflush=False)
    DestSession = sessionmaker(bind=dest_engine, autocommit=False, autoflush=False)
    return SourceSession(), DestSession()


def read_last_run(meta_file: str) -> datetime:
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            ts = f.read().strip()
            return datetime.fromisoformat(ts)
    except Exception:
        # Data bem antiga em UTC
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def write_last_run(meta_file: str, ts: datetime) -> None:
    dirpath = os.path.dirname(meta_file)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(meta_file, "w", encoding="utf-8") as f:
        f.write(ts.isoformat())


def chunked(query_iter: Iterable, size: int) -> Iterable[List]:
    batch: List = []
    for item in query_iter:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _batch_resolve_artigo_ids(
    db_src: Session, db_dst: Session, src_artigo_ids: List[int]
) -> Dict[int, int]:
    """
    Dado um lote de artigo_ids do source, retorna {src_artigo_id: dst_artigo_id}.
    Faz 2 queries (source + dest) em vez de 2N.
    hash_unico tem índice único — IN(...) já é rápido sem filtro de data.
    """
    if not src_artigo_ids:
        return {}
    src_rows = (
        db_src.query(ArtigoBruto.id, ArtigoBruto.hash_unico)
        .filter(ArtigoBruto.id.in_(src_artigo_ids))
        .all()
    )
    id_to_hash = {r.id: r.hash_unico for r in src_rows if r.hash_unico}
    if not id_to_hash:
        return {}
    hashes = list(set(id_to_hash.values()))
    dst_rows = (
        db_dst.query(ArtigoBruto.id, ArtigoBruto.hash_unico)
        .filter(ArtigoBruto.hash_unico.in_(hashes))
        .all()
    )
    hash_to_dst = {r.hash_unico: r.id for r in dst_rows}
    return {
        src_id: hash_to_dst[h]
        for src_id, h in id_to_hash.items()
        if h in hash_to_dst
    }


# ==============================================================================
# Migrações idempotentes e incrementais
# ==============================================================================


def migrate_clusters(db_src: Session, db_dst: Session, since: datetime, no_update: bool) -> Dict[int, int]:
    print("➡️ Migrando clusters (incremental)...")
    id_map: Dict[int, int] = {}

    # Busca apenas clusters criados/atualizados após 'since'
    q = db_src.query(ClusterEvento).filter(
        or_(ClusterEvento.created_at > since, ClusterEvento.updated_at > since)
    ).order_by(ClusterEvento.created_at.asc())

    for batch in chunked(q.yield_per(500), 500):
        for cluster in batch:
            day_start = datetime.combine(cluster.created_at.date(), datetime.min.time()) if cluster.created_at else None
            day_end = datetime.combine(cluster.created_at.date() + timedelta(days=1), datetime.min.time()) if cluster.created_at else None
            date_filters = [
                ClusterEvento.created_at >= day_start,
                ClusterEvento.created_at < day_end,
            ] if day_start else []
            existing = (
                db_dst.query(ClusterEvento)
                .filter(
                    ClusterEvento.titulo_cluster == cluster.titulo_cluster,
                    ClusterEvento.tag == cluster.tag,
                    *date_filters,
                )
                .first()
            )
            if existing:
                id_map[cluster.id] = existing.id
                if not no_update:
                    # Atualiza campos mutáveis
                    existing.resumo_cluster = cluster.resumo_cluster
                    existing.prioridade = cluster.prioridade
                    existing.embedding_medio = cluster.embedding_medio
                    existing.status = cluster.status or existing.status
                    existing.total_artigos = cluster.total_artigos or existing.total_artigos
                    existing.ultima_atualizacao = cluster.ultima_atualizacao or existing.ultima_atualizacao
                    existing.updated_at = cluster.updated_at or existing.updated_at
                    existing.tipo_fonte = cluster.tipo_fonte or existing.tipo_fonte  # NOVO: Atualiza tipo_fonte
                    # Notificacao incremental (resiliente a bancos sem essas colunas)
                    try:
                        existing.ja_notificado = getattr(cluster, 'ja_notificado', False) or False
                        if getattr(cluster, 'notificado_em', None):
                            existing.notificado_em = cluster.notificado_em
                    except Exception:
                        pass
                continue

            clone_kwargs = dict(
                titulo_cluster=cluster.titulo_cluster,
                resumo_cluster=cluster.resumo_cluster,
                tag=cluster.tag,
                prioridade=cluster.prioridade,
                embedding_medio=cluster.embedding_medio,
                created_at=cluster.created_at,
                updated_at=cluster.updated_at,
                status=cluster.status or "ativo",
                total_artigos=cluster.total_artigos or 0,
                ultima_atualizacao=cluster.ultima_atualizacao or cluster.created_at,
                tipo_fonte=cluster.tipo_fonte or 'nacional',
            )
            # Colunas de notificacao (podem nao existir em bancos antigos)
            try:
                clone_kwargs["ja_notificado"] = getattr(cluster, 'ja_notificado', False) or False
                clone_kwargs["notificado_em"] = getattr(cluster, 'notificado_em', None)
            except Exception:
                pass
            clone = ClusterEvento(**clone_kwargs)
            db_dst.add(clone)
            db_dst.commit()
            db_dst.refresh(clone)
            id_map[cluster.id] = clone.id

    db_dst.commit()
    print(f"✅ Clusters migrados/atualizados: {len(id_map)}")
    return id_map


def migrate_artigos(db_src: Session, db_dst: Session, since: datetime, cluster_id_map: Dict[int, int]) -> int:
    print("➡️ Migrando artigos (incremental)...")
    total = 0
    q = db_src.query(ArtigoBruto).filter(
        or_(ArtigoBruto.created_at > since, ArtigoBruto.processed_at > since)
    ).order_by(ArtigoBruto.created_at.asc())

    _light_cols = load_only(
        ArtigoBruto.id, ArtigoBruto.hash_unico,
        ArtigoBruto.cluster_id, ArtigoBruto.tipo_fonte, ArtigoBruto.embedding_v2,
    )

    for batch in chunked(q.yield_per(500), 500):
        batch_hashes = [a.hash_unico for a in batch if a.hash_unico]
        existing_map: Dict[str, ArtigoBruto] = {}
        if batch_hashes:
            rows = (
                db_dst.query(ArtigoBruto)
                .options(_light_cols)
                .filter(ArtigoBruto.hash_unico.in_(batch_hashes))
                .all()
            )
            for r in rows:
                existing_map[r.hash_unico] = r

        for artigo in batch:
            exists = existing_map.get(artigo.hash_unico)
            if exists:
                if artigo.cluster_id and not exists.cluster_id:
                    exists.cluster_id = cluster_id_map.get(artigo.cluster_id)
                if hasattr(artigo, 'tipo_fonte') and artigo.tipo_fonte and artigo.tipo_fonte != exists.tipo_fonte:
                    exists.tipo_fonte = artigo.tipo_fonte
                if artigo.embedding_v2 and not exists.embedding_v2:
                    exists.embedding_v2 = artigo.embedding_v2
                continue

            clone = ArtigoBruto(
                hash_unico=artigo.hash_unico,
                texto_bruto=artigo.texto_bruto,
                url_original=artigo.url_original,
                fonte_coleta=artigo.fonte_coleta,
                metadados=artigo.metadados or {},
                created_at=artigo.created_at,
                processed_at=artigo.processed_at,
                status=artigo.status or "pendente",
                titulo_extraido=artigo.titulo_extraido,
                texto_processado=artigo.texto_processado,
                jornal=artigo.jornal,
                autor=artigo.autor,
                pagina=artigo.pagina,
                data_publicacao=artigo.data_publicacao,
                categoria=artigo.categoria,
                tag=artigo.tag,
                prioridade=artigo.prioridade,
                relevance_score=artigo.relevance_score,
                relevance_reason=artigo.relevance_reason,
                embedding=artigo.embedding,
                embedding_v2=artigo.embedding_v2,
                cluster_id=cluster_id_map.get(artigo.cluster_id) if artigo.cluster_id else None,
                tipo_fonte=artigo.tipo_fonte or 'nacional',
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()
    print(f"✅ Artigos inseridos: {total}")
    return total


def migrate_sinteses(db_src: Session, db_dst: Session, since: datetime, no_update: bool) -> int:
    print("➡️ Migrando sínteses (incremental)...")
    total = 0
    q = db_src.query(SinteseExecutiva).filter(
        or_(SinteseExecutiva.created_at > since, SinteseExecutiva.updated_at > since)
    ).order_by(SinteseExecutiva.data_sintese.asc())

    for batch in chunked(q.yield_per(200), 200):
        for s in batch:
            existing = (
                db_dst.query(SinteseExecutiva)
                .filter(func.date(SinteseExecutiva.data_sintese) == func.date(s.data_sintese))
                .first()
            )
            if existing:
                if not no_update:
                    existing.texto_sintese = s.texto_sintese
                    existing.total_noticias_coletadas = s.total_noticias_coletadas
                    existing.total_eventos_unicos = s.total_eventos_unicos
                    existing.total_analises_criticas = s.total_analises_criticas
                    existing.total_monitoramento = s.total_monitoramento
                    existing.updated_at = s.updated_at or existing.updated_at
                continue
            clone = SinteseExecutiva(
                data_sintese=s.data_sintese,
                texto_sintese=s.texto_sintese,
                total_noticias_coletadas=s.total_noticias_coletadas,
                total_eventos_unicos=s.total_eventos_unicos,
                total_analises_criticas=s.total_analises_criticas,
                total_monitoramento=s.total_monitoramento,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()
    print(f"✅ Sínteses inseridas: {total}")
    return total


def migrate_configuracoes(db_src: Session, db_dst: Session, since: datetime, no_update: bool) -> int:
    print("➡️ Migrando configurações (incremental)...")
    total = 0
    q = db_src.query(ConfiguracaoColeta).filter(
        or_(ConfiguracaoColeta.created_at > since, ConfiguracaoColeta.updated_at > since)
    )

    for batch in chunked(q.yield_per(200), 200):
        for c in batch:
            existing = db_dst.query(ConfiguracaoColeta).filter(ConfiguracaoColeta.nome_coletor == c.nome_coletor).first()
            if existing:
                if not no_update:
                    existing.ativo = c.ativo
                    existing.configuracao = c.configuracao
                    existing.ultima_execucao = c.ultima_execucao
                    existing.proxima_execucao = c.proxima_execucao
                    existing.intervalo_minutos = c.intervalo_minutos
                    existing.updated_at = c.updated_at or existing.updated_at
                continue
            clone = ConfiguracaoColeta(
                nome_coletor=c.nome_coletor,
                ativo=c.ativo,
                configuracao=c.configuracao,
                ultima_execucao=c.ultima_execucao,
                proxima_execucao=c.proxima_execucao,
                intervalo_minutos=c.intervalo_minutos,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()
    print(f"✅ Configurações inseridas: {total}")
    return total


def migrate_cluster_alteracoes(db_src: Session, db_dst: Session, since: datetime, cluster_id_map: Dict[int, int]) -> int:
    print("➡️ Migrando alterações de clusters (incremental e idempotente)...")
    total = 0
    q = db_src.query(ClusterAlteracao).filter(ClusterAlteracao.timestamp > since).order_by(ClusterAlteracao.timestamp.asc())

    for batch in chunked(q.yield_per(500), 500):
        for alt in batch:
            mapped_cluster_id = cluster_id_map.get(alt.cluster_id)
            if not mapped_cluster_id:
                continue
            existing = (
                db_dst.query(ClusterAlteracao)
                .filter_by(
                    cluster_id=mapped_cluster_id,
                    timestamp=alt.timestamp,
                    campo_alterado=alt.campo_alterado,
                )
                .first()
            )
            if existing:
                continue
            clone = ClusterAlteracao(
                cluster_id=mapped_cluster_id,
                campo_alterado=alt.campo_alterado,
                valor_anterior=alt.valor_anterior,
                valor_novo=alt.valor_novo,
                motivo=alt.motivo,
                usuario=alt.usuario,
                timestamp=alt.timestamp,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()
    print(f"✅ Alterações inseridas: {total}")
    return total


def migrate_chat(db_src: Session, db_dst: Session, since: datetime, cluster_id_map: Dict[int, int]) -> Tuple[int, int]:
    print("➡️ Migrando chat (incremental e idempotente)...")
    # Sessões
    migrated_sessions: Dict[int, int] = {}
    q_sessions = db_src.query(ChatSession).filter(
        or_(ChatSession.created_at > since, ChatSession.updated_at > since)
    ).order_by(ChatSession.created_at.asc())

    for batch in chunked(q_sessions.yield_per(200), 200):
        for s in batch:
            mapped_cluster_id = cluster_id_map.get(s.cluster_id)
            if not mapped_cluster_id:
                continue
            existing = db_dst.query(ChatSession).filter(ChatSession.cluster_id == mapped_cluster_id).first()
            if existing:
                migrated_sessions[s.id] = existing.id
                continue
            clone = ChatSession(
                cluster_id=mapped_cluster_id,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            db_dst.add(clone)
            db_dst.commit()
            db_dst.refresh(clone)
            migrated_sessions[s.id] = clone.id

    # Mensagens
    count_msgs = 0
    q_msgs = db_src.query(ChatMessage).filter(ChatMessage.timestamp > since).order_by(ChatMessage.timestamp.asc())
    for batch in chunked(q_msgs.yield_per(500), 500):
        for m in batch:
            mapped_session_id = migrated_sessions.get(m.session_id)
            if not mapped_session_id:
                # Tenta encontrar sessão já existente mesmo que não esteja no mapa (execução antiga)
                # Não temos o cluster_id direto aqui, então pulamos para evitar inconsistência
                continue
            existing = (
                db_dst.query(ChatMessage)
                .filter_by(session_id=mapped_session_id, timestamp=m.timestamp, role=m.role, content=m.content)
                .first()
            )
            if existing:
                continue
            clone = ChatMessage(
                session_id=mapped_session_id,
                role=m.role,
                content=m.content,
                timestamp=m.timestamp,
            )
            db_dst.add(clone)
            count_msgs += 1
        db_dst.commit()

    print(f"✅ Sessões novas: {len(migrated_sessions)} | Mensagens inseridas: {count_msgs}")
    return len(migrated_sessions), count_msgs


def migrate_logs(db_src: Session, db_dst: Session, since: datetime, cluster_id_map: Dict[int, int], artigo_hash_to_id: Dict[str, int]) -> int:
    print("➡️ Migrando logs (incremental e idempotente)...")
    total = 0
    q = db_src.query(LogProcessamento).filter(LogProcessamento.timestamp > since).order_by(LogProcessamento.timestamp.asc())

    for batch in chunked(q.yield_per(1000), 1000):
        for log in batch:
            # Chave de negócio: (timestamp, componente, mensagem)
            existing = (
                db_dst.query(LogProcessamento)
                .filter_by(timestamp=log.timestamp, componente=log.componente, mensagem=log.mensagem)
                .first()
            )
            if existing:
                continue

            mapped_artigo_id: Optional[int] = None
            mapped_cluster_id: Optional[int] = None
            if getattr(log, "artigo_id", None):
                # Não temos acesso ao hash diretamente; portanto, não é trivial mapear
                # Tentativa: deixa None para evitar FK inválida
                mapped_artigo_id = None
            if getattr(log, "cluster_id", None):
                mapped_cluster_id = cluster_id_map.get(log.cluster_id)

            clone = LogProcessamento(
                timestamp=log.timestamp,
                nivel=log.nivel,
                componente=log.componente,
                mensagem=log.mensagem,
                detalhes=log.detalhes or {},
                artigo_id=mapped_artigo_id,
                cluster_id=mapped_cluster_id,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()
    print(f"✅ Logs inseridos: {total}")
    return total


def migrate_prompts(db_src: Session, db_dst: Session, since: datetime, no_update: bool) -> Dict[str, int]:
    """Migra tabelas de prompts configuráveis (tags, prioridades, templates)"""
    print("➡️ Migrando prompts configuráveis...")
    
    # Migra tags
    tags_count = 0
    q_tags = db_src.query(PromptTag).filter(PromptTag.updated_at > since).order_by(PromptTag.updated_at.asc())
    for tag in q_tags.yield_per(100):
        existing = db_dst.query(PromptTag).filter_by(nome=tag.nome).first()
        if existing and no_update:
            continue
            
        if existing:
            # Atualiza tag existente
            existing.descricao = tag.descricao
            existing.exemplos = tag.exemplos
            existing.ordem = tag.ordem
            existing.tipo_fonte = tag.tipo_fonte or existing.tipo_fonte  # NOVO: Atualiza tipo_fonte
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Cria nova tag
            clone = PromptTag(
                nome=tag.nome,
                descricao=tag.descricao,
                exemplos=tag.exemplos,
                ordem=tag.ordem,
                tipo_fonte=tag.tipo_fonte or 'nacional',  # NOVO: Campo crítico para separação nacional/internacional
                created_at=tag.created_at,
                updated_at=tag.updated_at
            )
            db_dst.add(clone)
            tags_count += 1
    
    # Migra itens de prioridade
    prioridades_count = 0
    q_prioridades = db_src.query(PromptPrioridadeItem).filter(PromptPrioridadeItem.updated_at > since).order_by(PromptPrioridadeItem.updated_at.asc())
    for prioridade in q_prioridades.yield_per(100):
        existing = db_dst.query(PromptPrioridadeItem).filter_by(
            nivel=prioridade.nivel, 
            texto=prioridade.texto
        ).first()
        
        if existing and no_update:
            continue
            
        if existing:
            # Atualiza item existente
            existing.texto = prioridade.texto
            existing.ordem = prioridade.ordem
            existing.tipo_fonte = prioridade.tipo_fonte or existing.tipo_fonte  # NOVO: Atualiza tipo_fonte
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Cria novo item
            clone = PromptPrioridadeItem(
                nivel=prioridade.nivel,
                texto=prioridade.texto,
                ordem=prioridade.ordem,
                tipo_fonte=prioridade.tipo_fonte or 'nacional',  # NOVO: Campo crítico para separação nacional/internacional
                created_at=prioridade.created_at,
                updated_at=prioridade.updated_at
            )
            db_dst.add(clone)
            prioridades_count += 1
    
    # Migra templates
    templates_count = 0
    q_templates = db_src.query(PromptTemplate).filter(PromptTemplate.updated_at > since).order_by(PromptTemplate.updated_at.asc())
    for template in q_templates.yield_per(100):
        existing = db_dst.query(PromptTemplate).filter_by(chave=template.chave).first()
        if existing and no_update:
            continue
            
        if existing:
            # Atualiza template existente
            existing.conteudo = template.conteudo
            existing.descricao = template.descricao  # NOVO: Atualiza descrição
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Cria novo template
            clone = PromptTemplate(
                chave=template.chave,
                descricao=template.descricao,
                conteudo=template.conteudo,
                created_at=template.created_at,
                updated_at=template.updated_at
            )
            db_dst.add(clone)
            templates_count += 1
    
    db_dst.commit()
    
    print(f"✅ Tags: {tags_count} | Prioridades: {prioridades_count} | Templates: {templates_count}")
    return {
        'tags': tags_count,
        'prioridades': prioridades_count,
        'templates': templates_count
    }


# ==============================================================================
# Migrações v2.0: Grafo, Feedback, Estagiário, Research
# ==============================================================================


def migrate_graph_entities(db_src: Session, db_dst: Session, since: datetime, no_update: bool) -> Dict[str, str]:
    """Migra graph_entities (nós do grafo). DEVE rodar ANTES de graph_edges (FK)."""
    print("➡️ Migrando entidades do grafo (incremental)...")
    uuid_map: Dict[str, str] = {}  # source UUID string -> dest UUID string
    total_new = 0

    q = db_src.query(GraphEntity).filter(
        or_(GraphEntity.created_at > since, GraphEntity.updated_at > since)
    ).order_by(GraphEntity.created_at.asc())

    for batch in chunked(q.yield_per(500), 500):
        for entity in batch:
            # Chave de negócio: (canonical_name, entity_type) é UNIQUE
            existing = (
                db_dst.query(GraphEntity)
                .filter_by(canonical_name=entity.canonical_name, entity_type=entity.entity_type)
                .first()
            )
            if existing:
                uuid_map[str(entity.id)] = str(existing.id)
                if not no_update:
                    existing.name = entity.name
                    existing.description = entity.description
                    existing.aliases = entity.aliases
                    existing.updated_at = entity.updated_at
                continue

            clone = GraphEntity(
                id=entity.id,  # Preserva UUID original
                name=entity.name,
                canonical_name=entity.canonical_name,
                entity_type=entity.entity_type,
                description=entity.description,
                aliases=entity.aliases or [],
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
            db_dst.add(clone)
            uuid_map[str(entity.id)] = str(entity.id)
            total_new += 1
        db_dst.commit()

    print(f"✅ Entidades do grafo: {total_new} novas | {len(uuid_map)} total mapeadas")
    return uuid_map


def migrate_graph_edges(
    db_src: Session, db_dst: Session, since: datetime,
    entity_uuid_map: Dict[str, str],
) -> int:
    """Migra graph_edges (arestas). DEVE rodar APÓS graph_entities e artigos."""
    import uuid as uuid_mod

    print("➡️ Migrando arestas do grafo (incremental)...")
    total = 0
    skipped = 0

    q = db_src.query(GraphEdge).filter(GraphEdge.created_at > since).order_by(GraphEdge.created_at.asc())

    for batch in chunked(q.yield_per(500), 500):
        batch_artigo_ids = list(set(e.artigo_id for e in batch))
        artigo_map = _batch_resolve_artigo_ids(db_src, db_dst, batch_artigo_ids)

        for edge in batch:
            mapped_entity_id_str = entity_uuid_map.get(str(edge.entity_id))
            if not mapped_entity_id_str:
                skipped += 1
                continue

            dst_artigo_id = artigo_map.get(edge.artigo_id)
            if not dst_artigo_id:
                skipped += 1
                continue

            mapped_entity_uuid = uuid_mod.UUID(mapped_entity_id_str)
            existing = (
                db_dst.query(GraphEdge)
                .filter_by(artigo_id=dst_artigo_id, entity_id=mapped_entity_uuid)
                .first()
            )
            if existing:
                continue

            clone = GraphEdge(
                artigo_id=dst_artigo_id,
                entity_id=mapped_entity_uuid,
                relation_type=edge.relation_type,
                sentiment_score=edge.sentiment_score,
                context_snippet=edge.context_snippet,
                confidence=edge.confidence,
                created_at=edge.created_at,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()

    print(f"✅ Arestas do grafo inseridas: {total} (skipped: {skipped})")
    return total


def migrate_feedback(db_src: Session, db_dst: Session, since: datetime) -> int:
    """Migra feedback (likes/dislikes) de artigos."""
    print("➡️ Migrando feedback (incremental)...")
    total = 0

    q = db_src.query(FeedbackNoticia).filter(FeedbackNoticia.created_at > since).order_by(FeedbackNoticia.created_at.asc())

    for batch in chunked(q.yield_per(500), 500):
        batch_artigo_ids = list(set(fb.artigo_id for fb in batch))
        artigo_map = _batch_resolve_artigo_ids(db_src, db_dst, batch_artigo_ids)

        for fb in batch:
            dst_artigo_id = artigo_map.get(fb.artigo_id)
            if not dst_artigo_id:
                continue

            existing = (
                db_dst.query(FeedbackNoticia)
                .filter_by(artigo_id=dst_artigo_id, feedback=fb.feedback, created_at=fb.created_at)
                .first()
            )
            if existing:
                continue

            clone = FeedbackNoticia(
                artigo_id=dst_artigo_id,
                feedback=fb.feedback,
                processed=fb.processed,
                created_at=fb.created_at,
            )
            db_dst.add(clone)
            total += 1
        db_dst.commit()

    print(f"✅ Feedbacks inseridos: {total}")
    return total


def migrate_estagiario_chat(db_src: Session, db_dst: Session, since: datetime) -> Tuple[int, int]:
    """Migra sessões e mensagens do Estagiário."""
    print("➡️ Migrando chat do Estagiário (incremental)...")
    session_map: Dict[int, int] = {}

    # Sessões
    q_sessions = db_src.query(EstagiarioChatSession).filter(
        EstagiarioChatSession.created_at > since
    ).order_by(EstagiarioChatSession.created_at.asc())

    for s in q_sessions.yield_per(200):
        # Deduplica por data_referencia
        existing = (
            db_dst.query(EstagiarioChatSession)
            .filter_by(data_referencia=s.data_referencia)
            .first()
        ) if hasattr(s, 'data_referencia') and s.data_referencia else None

        if existing:
            session_map[s.id] = existing.id
            continue

        clone = EstagiarioChatSession(
            data_referencia=getattr(s, 'data_referencia', None),
            created_at=s.created_at,
        )
        db_dst.add(clone)
        db_dst.commit()
        db_dst.refresh(clone)
        session_map[s.id] = clone.id

    # Mensagens
    count_msgs = 0
    q_msgs = db_src.query(EstagiarioChatMessage).filter(
        EstagiarioChatMessage.timestamp > since
    ).order_by(EstagiarioChatMessage.timestamp.asc())

    for batch in chunked(q_msgs.yield_per(500), 500):
        for m in batch:
            mapped_session_id = session_map.get(m.session_id)
            if not mapped_session_id:
                continue
            existing = (
                db_dst.query(EstagiarioChatMessage)
                .filter_by(session_id=mapped_session_id, timestamp=m.timestamp, role=m.role)
                .first()
            )
            if existing:
                continue
            clone = EstagiarioChatMessage(
                session_id=mapped_session_id,
                role=m.role,
                content=m.content,
                timestamp=m.timestamp,
            )
            db_dst.add(clone)
            count_msgs += 1
        db_dst.commit()

    print(f"✅ Estagiário: {len(session_map)} sessões | {count_msgs} mensagens")
    return len(session_map), count_msgs


def migrate_research_jobs(
    db_src: Session, db_dst: Session, since: datetime, cluster_id_map: Dict[int, int]
) -> Tuple[int, int]:
    """Migra jobs de pesquisa (deep research e social research)."""
    print("➡️ Migrando research jobs (incremental)...")
    deep_count = 0
    social_count = 0

    # Deep Research
    q_deep = db_src.query(DeepResearchJob).filter(DeepResearchJob.created_at > since).order_by(DeepResearchJob.created_at.asc())
    for job in q_deep.yield_per(200):
        mapped_cluster_id = cluster_id_map.get(job.cluster_id)
        if not mapped_cluster_id:
            continue
        existing = (
            db_dst.query(DeepResearchJob)
            .filter_by(cluster_id=mapped_cluster_id, created_at=job.created_at)
            .first()
        )
        if existing:
            continue
        clone = DeepResearchJob(
            cluster_id=mapped_cluster_id,
            query=job.query,
            status=job.status,
            result_json=job.result_json,
            error_message=getattr(job, 'error_message', None),
            created_at=job.created_at,
            updated_at=getattr(job, 'updated_at', None),
        )
        db_dst.add(clone)
        deep_count += 1
    db_dst.commit()

    # Social Research
    q_social = db_src.query(SocialResearchJob).filter(SocialResearchJob.created_at > since).order_by(SocialResearchJob.created_at.asc())
    for job in q_social.yield_per(200):
        mapped_cluster_id = cluster_id_map.get(job.cluster_id)
        if not mapped_cluster_id:
            continue
        existing = (
            db_dst.query(SocialResearchJob)
            .filter_by(cluster_id=mapped_cluster_id, created_at=job.created_at)
            .first()
        )
        if existing:
            continue
        clone = SocialResearchJob(
            cluster_id=mapped_cluster_id,
            query=job.query,
            status=job.status,
            result_json=job.result_json,
            error_message=getattr(job, 'error_message', None),
            created_at=job.created_at,
            updated_at=getattr(job, 'updated_at', None),
        )
        db_dst.add(clone)
        social_count += 1
    db_dst.commit()

    print(f"✅ Research: {deep_count} deep | {social_count} social")
    return deep_count, social_count


# ==============================================================================
# CLI
# ==============================================================================


# ==============================================================================
# Migração: Usuários e dados multi-tenant (v3.0)
# ==============================================================================


def migrate_usuarios(
    db_src: Session, db_dst: Session, since: datetime, no_update: bool = False
) -> Dict[int, int]:
    """Migra usuarios. Retorna mapa {src_id: dst_id}."""
    id_map: Dict[int, int] = {}
    try:
        rows = db_src.query(Usuario).filter(Usuario.created_at >= since).all()
    except Exception as e:
        db_src.rollback()
        if "does not exist" in str(e) or "UndefinedTable" in str(type(e).__name__):
            print("  ⏭️ Tabela 'usuarios' nao existe. Pulando migracao multi-tenant.")
            return id_map
        raise
    if not rows:
        print("  ⏭️ Nenhum usuário novo.")
        return id_map
    print(f"  📦 Migrando {len(rows)} usuarios...")
    for u in rows:
        existing = db_dst.query(Usuario).filter(Usuario.email == u.email).first()
        if existing:
            id_map[u.id] = existing.id
            if not no_update:
                existing.nome = u.nome
                existing.senha_hash = u.senha_hash
                existing.role = u.role
                existing.ativo = u.ativo
                existing.updated_at = u.updated_at
        else:
            new_u = Usuario(
                nome=u.nome, email=u.email, senha_hash=u.senha_hash,
                role=u.role, ativo=u.ativo, created_at=u.created_at, updated_at=u.updated_at,
            )
            db_dst.add(new_u)
            db_dst.flush()
            id_map[u.id] = new_u.id
    db_dst.commit()
    print(f"  ✅ {len(id_map)} usuarios migrados.")
    return id_map


def migrate_preferencias_usuario(
    db_src: Session, db_dst: Session, since: datetime, user_id_map: Dict[int, int]
) -> None:
    """Migra preferencias de usuario."""
    try:
        rows = db_src.query(PreferenciaUsuario).filter(PreferenciaUsuario.updated_at >= since).all()
    except Exception as e:
        if "does not exist" in str(e):
            print("  ⏭️ Tabela 'preferencias_usuario' nao existe. Pulando.")
            db_src.rollback()
            return
        raise
    if not rows:
        print("  ⏭️ Nenhuma preferência nova.")
        return
    print(f"  📦 Migrando {len(rows)} preferencias...")
    for p in rows:
        dst_uid = user_id_map.get(p.user_id)
        if not dst_uid:
            continue
        existing = db_dst.query(PreferenciaUsuario).filter(PreferenciaUsuario.user_id == dst_uid).first()
        if existing:
            for col in ["tags_interesse", "tags_ignoradas", "fontes_ignoradas", "prioridade_minima",
                         "tipo_fonte_preferido", "tamanho_resumo", "config_extra"]:
                setattr(existing, col, getattr(p, col))
            existing.updated_at = p.updated_at
        else:
            new_p = PreferenciaUsuario(
                user_id=dst_uid, tags_interesse=p.tags_interesse, tags_ignoradas=p.tags_ignoradas,
                fontes_ignoradas=p.fontes_ignoradas, prioridade_minima=p.prioridade_minima,
                tipo_fonte_preferido=p.tipo_fonte_preferido, tamanho_resumo=p.tamanho_resumo,
                config_extra=p.config_extra, created_at=p.created_at, updated_at=p.updated_at,
            )
            db_dst.add(new_p)
    db_dst.commit()
    print(f"  ✅ Preferências migradas.")


def migrate_templates_resumo(
    db_src: Session, db_dst: Session, since: datetime, user_id_map: Dict[int, int]
) -> Dict[int, int]:
    """Migra templates de resumo. Retorna mapa {src_id: dst_id}."""
    tpl_map: Dict[int, int] = {}
    try:
        rows = db_src.query(TemplateResumoUsuario).filter(TemplateResumoUsuario.updated_at >= since).all()
    except Exception as e:
        if "does not exist" in str(e):
            print("  ⏭️ Tabela 'templates_resumo_usuario' nao existe. Pulando.")
            db_src.rollback()
            return tpl_map
        raise
    if not rows:
        print("  ⏭️ Nenhum template novo.")
        return tpl_map
    print(f"  📦 Migrando {len(rows)} templates de resumo...")
    for t in rows:
        dst_uid = None
        if t.criado_por_user_id is not None:
            dst_uid = user_id_map.get(t.criado_por_user_id)
            if not dst_uid:
                continue
        existing = db_dst.query(TemplateResumoUsuario).filter(
            TemplateResumoUsuario.nome == t.nome,
            TemplateResumoUsuario.criado_por_user_id == dst_uid,
        ).first()
        if existing:
            tpl_map[t.id] = existing.id
            existing.system_prompt = t.system_prompt
            existing.publico = t.publico
            existing.tools_habilitadas = t.tools_habilitadas
            existing.restricoes = t.restricoes
            existing.updated_at = t.updated_at
        else:
            new_t = TemplateResumoUsuario(
                nome=t.nome, descricao=t.descricao, criado_por_user_id=dst_uid,
                publico=t.publico, system_prompt=t.system_prompt,
                tools_habilitadas=t.tools_habilitadas, restricoes=t.restricoes,
                created_at=t.created_at, updated_at=t.updated_at,
            )
            db_dst.add(new_t)
            db_dst.flush()
            tpl_map[t.id] = new_t.id
    db_dst.commit()
    print(f"  ✅ {len(tpl_map)} templates migrados.")
    return tpl_map


def migrate_resumos_usuario(
    db_src: Session, db_dst: Session, since: datetime,
    user_id_map: Dict[int, int], tpl_id_map: Dict[int, int]
) -> None:
    """Migra resumos de usuario."""
    try:
        rows = db_src.query(ResumoUsuario).filter(ResumoUsuario.created_at >= since).all()
    except Exception as e:
        if "does not exist" in str(e):
            print("  ⏭️ Tabela 'resumos_usuario' nao existe. Pulando.")
            db_src.rollback()
            return
        raise
    if not rows:
        print("  ⏭️ Nenhum resumo de usuário novo.")
        return
    print(f"  📦 Migrando {len(rows)} resumos de usuário...")
    for r in rows:
        dst_uid = None
        if r.user_id is not None:
            dst_uid = user_id_map.get(r.user_id)
            if not dst_uid:
                continue
        dst_tpl = tpl_id_map.get(r.template_id) if r.template_id else None
        existing = db_dst.query(ResumoUsuario).filter(
            ResumoUsuario.user_id == dst_uid,
            func.date(ResumoUsuario.data_referencia) == func.date(r.data_referencia),
            ResumoUsuario.created_at == r.created_at,
        ).first()
        if existing:
            continue
        new_r = ResumoUsuario(
            user_id=dst_uid, data_referencia=r.data_referencia, template_id=dst_tpl,
            clusters_avaliados_ids=r.clusters_avaliados_ids, clusters_escolhidos_ids=r.clusters_escolhidos_ids,
            texto_gerado=r.texto_gerado, texto_whatsapp=r.texto_whatsapp,
            prompt_version=r.prompt_version, metadados=r.metadados, created_at=r.created_at,
        )
        db_dst.add(new_r)
    db_dst.commit()
    print(f"  ✅ Resumos de usuário migrados.")


def main() -> None:
    default_meta = os.path.join(os.path.dirname(__file__), "last_migration.txt")

    parser = argparse.ArgumentParser(description="Migração incremental e idempotente: local -> Heroku")
    parser.add_argument("--source", default=os.getenv("SOURCE_DATABASE_URL", "postgresql+psycopg2://postgres_local@localhost:5433/devdb"))
    parser.add_argument("--dest", default=os.getenv("DEST_DATABASE_URL", ""))
    parser.add_argument("--meta-file", default=default_meta, help="Arquivo para armazenar o último timestamp migrado")
    parser.add_argument("--since", default=None, help="Timestamp ISO (UTC) para início da migração")
    parser.add_argument("--no-update-existing", action="store_true", help="Não atualiza registros já existentes")
    parser.add_argument("--include-logs", action="store_true", help="Migrar logs")
    parser.add_argument("--include-chat", action="store_true", help="Migrar chat")
    parser.add_argument("--include-prompts", action="store_true", help="Migrar prompts configuráveis")
    parser.add_argument("--include-graph", action="store_true", help="Migrar grafo v2 (entidades e arestas)")
    parser.add_argument("--include-feedback", action="store_true", help="Migrar feedback (likes/dislikes)")
    parser.add_argument("--include-research", action="store_true", help="Migrar research jobs")
    parser.add_argument("--include-estagiario", action="store_true", help="Migrar chat do Estagiário")
    parser.add_argument("--include-usuarios", action="store_true", help="Migrar usuarios, preferencias, templates e resumos")
    parser.add_argument("--include-all", action="store_true", help="Migrar TODAS as entidades (equivale a todas as flags --include-*)")
    parser.add_argument("--only", default="", help="Lista de entidades a migrar (ex: clusters,artigos,sinteses,configs,alteracoes,chat,logs,prompts,graph,feedback,research,estagiario,usuarios)")

    args = parser.parse_args()
    if not args.dest:
        raise SystemExit("Informe --dest com a URL do Postgres do Heroku")

    # Define escopo
    only_set: Set[str] = set([s.strip().lower() for s in args.only.split(",") if s.strip()])
    def want(name: str) -> bool:
        return not only_set or name in only_set

    # Timestamp base
    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        since = read_last_run(args.meta_file)

    print(f"⏱️ Rodando incremental desde: {since.isoformat()}")
    db_src, db_dst = create_sessions(args.source, args.dest)

    # --include-all habilita todas as flags
    if args.include_all:
        args.include_chat = True
        args.include_prompts = True
        args.include_graph = True
        args.include_feedback = True
        args.include_research = True
        args.include_estagiario = True
        args.include_usuarios = True

    try:
        cluster_id_map: Dict[int, int] = {}
        if want("clusters"):
            cluster_id_map = migrate_clusters(db_src, db_dst, since, args.no_update_existing)
        else:
            # Se clusters não forem migrados, ainda precisamos construir um mapa mínimo
            # a partir de chaves de negócio ao migrar artigos/alterações/chat
            pass

        if want("artigos"):
            migrate_artigos(db_src, db_dst, since, cluster_id_map)

        if want("sinteses"):
            migrate_sinteses(db_src, db_dst, since, args.no_update_existing)

        if want("configs"):
            migrate_configuracoes(db_src, db_dst, since, args.no_update_existing)

        if want("alteracoes"):
            migrate_cluster_alteracoes(db_src, db_dst, since, cluster_id_map)

        if (args.include_chat or args.include_all) and want("chat"):
            migrate_chat(db_src, db_dst, since, cluster_id_map)

        if (args.include_logs) and want("logs"):
            # REMOVIDO: Migração de logs para tornar o processo mais rápido
            # Os logs não são essenciais para o funcionamento do sistema em produção
            print("⏭️ Pulando migração de logs (não essencial para produção)")

        if (args.include_prompts or args.include_all) and want("prompts"):
            migrate_prompts(db_src, db_dst, since, args.no_update_existing)

        # ---- v2.0: Grafo, Feedback, Estagiário, Research ----

        if (args.include_graph or args.include_all) and want("graph"):
            entity_uuid_map = migrate_graph_entities(db_src, db_dst, since, args.no_update_existing)
            migrate_graph_edges(db_src, db_dst, since, entity_uuid_map)

        if (args.include_feedback or args.include_all) and want("feedback"):
            migrate_feedback(db_src, db_dst, since)

        if (args.include_estagiario or args.include_all) and want("estagiario"):
            migrate_estagiario_chat(db_src, db_dst, since)

        if (args.include_research or args.include_all) and want("research"):
            migrate_research_jobs(db_src, db_dst, since, cluster_id_map)

        # ---- v3.0: Usuários Multi-Tenant ----
        if (args.include_usuarios or args.include_all) and want("usuarios"):
            user_id_map = migrate_usuarios(db_src, db_dst, since, args.no_update_existing)
            if user_id_map is not None:
                try:
                    migrate_preferencias_usuario(db_src, db_dst, since, user_id_map)
                    tpl_id_map = migrate_templates_resumo(db_src, db_dst, since, user_id_map)
                    migrate_resumos_usuario(db_src, db_dst, since, user_id_map, tpl_id_map)
                except Exception as e:
                    if "does not exist" in str(e):
                        db_src.rollback()
                        print(f"  ⏭️ Tabelas multi-tenant incompletas. Pulando.")
                    else:
                        raise

        # Atualiza timestamp somente se nenhuma exceção ocorreu
        write_last_run(args.meta_file, datetime.now(timezone.utc))
        print("🎯 Migração incremental concluída com sucesso.")
    finally:
        db_src.close()
        db_dst.close()


if __name__ == "__main__":
    main()


