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
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, and_, or_, text
from sqlalchemy.orm import sessionmaker, Session

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


def create_sessions(source_url: str, dest_url: str) -> Tuple[Session, Session]:
    source_engine = create_engine(normalize_db_url(source_url), pool_pre_ping=True)
    dest_engine = create_engine(normalize_db_url(dest_url), pool_pre_ping=True)

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
            created_date = cluster.created_at.date() if cluster.created_at else None
            existing = (
                db_dst.query(ClusterEvento)
                .filter(
                    ClusterEvento.titulo_cluster == cluster.titulo_cluster,
                    ClusterEvento.tag == cluster.tag,
                    func.date(ClusterEvento.created_at) == created_date,
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
                continue

            clone = ClusterEvento(
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
            )
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

    for batch in chunked(q.yield_per(500), 500):
        for artigo in batch:
            exists = db_dst.query(ArtigoBruto).filter(ArtigoBruto.hash_unico == artigo.hash_unico).first()
            if exists:
                # Atualiza vínculo de cluster se necessário
                if artigo.cluster_id and not exists.cluster_id:
                    exists.cluster_id = cluster_id_map.get(artigo.cluster_id)
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
                cluster_id=cluster_id_map.get(artigo.cluster_id) if artigo.cluster_id else None,
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
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Cria nova tag
            clone = PromptTag(
                nome=tag.nome,
                descricao=tag.descricao,
                exemplos=tag.exemplos,
                ordem=tag.ordem,
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
            item=prioridade.item
        ).first()
        
        if existing and no_update:
            continue
            
        if existing:
            # Atualiza item existente
            existing.descricao = prioridade.descricao
            existing.ordem = prioridade.ordem
            existing.updated_at = datetime.now(timezone.utc)
        else:
            # Cria novo item
            clone = PromptPrioridadeItem(
                nivel=prioridade.nivel,
                item=prioridade.item,
                descricao=prioridade.descricao,
                ordem=prioridade.ordem,
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
# CLI
# ==============================================================================


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
    parser.add_argument("--only", default="", help="Lista de entidades a migrar (ex: clusters,artigos,sinteses,configs,alteracoes,chat,logs,prompts)")

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

        if args.include_chat and want("chat"):
            migrate_chat(db_src, db_dst, since, cluster_id_map)

        if args.include_logs and want("logs"):
            migrate_logs(db_src, db_dst, since, cluster_id_map, artigo_hash_to_id={})

        if args.include_prompts and want("prompts"):
            migrate_prompts(db_src, db_dst, since, args.no_update_existing)

        # Atualiza timestamp somente se nenhuma exceção ocorreu
        write_last_run(args.meta_file, datetime.now(timezone.utc))
        print("🎯 Migração incremental concluída com sucesso.")
    finally:
        db_src.close()
        db_dst.close()


if __name__ == "__main__":
    main()


