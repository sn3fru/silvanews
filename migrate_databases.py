"""
Script de migração: copia dados do Postgres local para o Postgres do Heroku.

Uso:
  conda activate pymc2
  python -m btg_alphafeed.migrate_databases \
    --source postgresql+psycopg2://postgres_local@localhost:5433/devdb \
    --dest postgres://<usuario>:<senha>@<host>:5432/<db> \
    --include-logs --include-chat

Por padrão migra: clusters, artigos, sínteses e configurações.
Logs e chat podem ser incluídos via flags (desligados por padrão).
"""

from __future__ import annotations

import os
import sys
import argparse
from typing import Dict, Optional, Tuple, List
from datetime import datetime

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

try:
    # Executando como módulo dentro do pacote btg_alphafeed
    from backend.database import (
        Base,
        ArtigoBruto,
        ClusterEvento,
        SinteseExecutiva,
        LogProcessamento,
        ConfiguracaoColeta,
        ChatSession,
        ChatMessage,
        ClusterAlteracao,
    )
except ImportError:
    # Execução direta fora do pacote
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
    )


def normalize_db_url(url: str) -> str:
    """
    Converte postgres:// para postgresql+psycopg2:// quando necessário.
    Remove caracteres residuais (ex.: barra/pipe no final).
    """
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

    # Garante que o destino tenha as tabelas
    Base.metadata.create_all(bind=dest_engine)

    SourceSession = sessionmaker(bind=source_engine, autocommit=False, autoflush=False)
    DestSession = sessionmaker(bind=dest_engine, autocommit=False, autoflush=False)
    return SourceSession(), DestSession()


def migrate_clusters(db_src: Session, db_dst: Session) -> Dict[int, int]:
    """Migra clusters, retornando um mapa id_origem -> id_destino."""
    print("➡️ Migrando clusters...")
    id_map: Dict[int, int] = {}
    clusters: List[ClusterEvento] = db_src.query(ClusterEvento).order_by(ClusterEvento.created_at.asc()).all()
    for cluster in clusters:
        # Identidade lógica: mesmo título, tag e mesma data (UTC) do created_at
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
            continue

        clone = ClusterEvento(
            titulo_cluster=cluster.titulo_cluster,
            resumo_cluster=cluster.resumo_cluster,
            tag=cluster.tag,
            prioridade=cluster.prioridade,
            embedding_medio=cluster.embedding_medio,
            created_at=cluster.created_at or datetime.utcnow(),
            updated_at=cluster.updated_at or datetime.utcnow(),
            status=cluster.status or "ativo",
            total_artigos=cluster.total_artigos or 0,
            ultima_atualizacao=cluster.ultima_atualizacao or datetime.utcnow(),
        )
        db_dst.add(clone)
        db_dst.commit()
        db_dst.refresh(clone)
        id_map[cluster.id] = clone.id
    print(f"✅ Clusters migrados: {len(id_map)}")
    return id_map


def migrate_artigos(db_src: Session, db_dst: Session, cluster_id_map: Dict[int, int]) -> int:
    """Migra artigos com deduplicação por hash_unico e re-mapeia cluster_id."""
    print("➡️ Migrando artigos...")
    total_migrados = 0
    artigos: List[ArtigoBruto] = db_src.query(ArtigoBruto).order_by(ArtigoBruto.created_at.asc()).all()
    for artigo in artigos:
        # Skip se já existe por hash_unico
        exists = db_dst.query(ArtigoBruto).filter(ArtigoBruto.hash_unico == artigo.hash_unico).first()
        if exists:
            continue

        clone = ArtigoBruto(
            hash_unico=artigo.hash_unico,
            texto_bruto=artigo.texto_bruto,
            url_original=artigo.url_original,
            fonte_coleta=artigo.fonte_coleta,
            metadados=artigo.metadados or {},
            created_at=artigo.created_at or datetime.utcnow(),
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
        total_migrados += 1
        if total_migrados % 200 == 0:
            db_dst.commit()
    db_dst.commit()
    print(f"✅ Artigos migrados: {total_migrados}")
    return total_migrados


def migrate_sinteses(db_src: Session, db_dst: Session) -> int:
    """Upsert por data_sintese."""
    print("➡️ Migrando sínteses executivas...")
    count = 0
    itens: List[SinteseExecutiva] = db_src.query(SinteseExecutiva).order_by(SinteseExecutiva.data_sintese.asc()).all()
    for s in itens:
        existing = (
            db_dst.query(SinteseExecutiva)
            .filter(func.date(SinteseExecutiva.data_sintese) == func.date(s.data_sintese))
            .first()
        )
        if existing:
            existing.texto_sintese = s.texto_sintese
            existing.total_noticias_coletadas = s.total_noticias_coletadas
            existing.total_eventos_unicos = s.total_eventos_unicos
            existing.total_analises_criticas = s.total_analises_criticas
            existing.total_monitoramento = s.total_monitoramento
            existing.updated_at = s.updated_at or datetime.utcnow()
        else:
            clone = SinteseExecutiva(
                data_sintese=s.data_sintese,
                texto_sintese=s.texto_sintese,
                total_noticias_coletadas=s.total_noticias_coletadas,
                total_eventos_unicos=s.total_eventos_unicos,
                total_analises_criticas=s.total_analises_criticas,
                total_monitoramento=s.total_monitoramento,
                created_at=s.created_at or datetime.utcnow(),
                updated_at=s.updated_at or datetime.utcnow(),
            )
            db_dst.add(clone)
        count += 1
        if count % 200 == 0:
            db_dst.commit()
    db_dst.commit()
    print(f"✅ Sínteses migradas: {count}")
    return count


def migrate_configuracoes(db_src: Session, db_dst: Session) -> int:
    """Upsert por nome_coletor."""
    print("➡️ Migrando configurações de coleta...")
    count = 0
    itens: List[ConfiguracaoColeta] = db_src.query(ConfiguracaoColeta).all()
    for c in itens:
        existing = db_dst.query(ConfiguracaoColeta).filter(ConfiguracaoColeta.nome_coletor == c.nome_coletor).first()
        if existing:
            existing.ativo = c.ativo
            existing.configuracao = c.configuracao
            existing.ultima_execucao = c.ultima_execucao
            existing.proxima_execucao = c.proxima_execucao
            existing.intervalo_minutos = c.intervalo_minutos
            existing.updated_at = c.updated_at or datetime.utcnow()
        else:
            clone = ConfiguracaoColeta(
                nome_coletor=c.nome_coletor,
                ativo=c.ativo,
                configuracao=c.configuracao,
                ultima_execucao=c.ultima_execucao,
                proxima_execucao=c.proxima_execucao,
                intervalo_minutos=c.intervalo_minutos,
                created_at=c.created_at or datetime.utcnow(),
                updated_at=c.updated_at or datetime.utcnow(),
            )
            db_dst.add(clone)
        count += 1
    db_dst.commit()
    print(f"✅ Configurações migradas: {count}")
    return count


def migrate_logs(db_src: Session, db_dst: Session) -> int:
    print("➡️ Migrando logs (pode ser grande)...")
    count = 0
    logs: List[LogProcessamento] = db_src.query(LogProcessamento).order_by(LogProcessamento.timestamp.asc()).all()
    for log in logs:
        clone = LogProcessamento(
            timestamp=log.timestamp,
            nivel=log.nivel,
            componente=log.componente,
            mensagem=log.mensagem,
            detalhes=log.detalhes or {},
            artigo_id=None,  # não mapeamos artigo_id aqui para evitar FK quebrada
            cluster_id=None,  # idem
        )
        db_dst.add(clone)
        count += 1
        if count % 500 == 0:
            db_dst.commit()
    db_dst.commit()
    print(f"✅ Logs migrados: {count}")
    return count


def migrate_cluster_alteracoes(db_src: Session, db_dst: Session, cluster_id_map: Dict[int, int]) -> int:
    print("➡️ Migrando alterações de clusters...")
    count = 0
    itens: List[ClusterAlteracao] = db_src.query(ClusterAlteracao).order_by(ClusterAlteracao.timestamp.asc()).all()
    for alt in itens:
        clone = ClusterAlteracao(
            cluster_id=cluster_id_map.get(alt.cluster_id, None),
            campo_alterado=alt.campo_alterado,
            valor_anterior=alt.valor_anterior,
            valor_novo=alt.valor_novo,
            motivo=alt.motivo,
            usuario=alt.usuario,
            timestamp=alt.timestamp,
        )
        db_dst.add(clone)
        count += 1
        if count % 200 == 0:
            db_dst.commit()
    db_dst.commit()
    print(f"✅ Alterações migradas: {count}")
    return count


def migrate_chat(db_src: Session, db_dst: Session, cluster_id_map: Dict[int, int]) -> int:
    print("➡️ Migrando chat (sessões e mensagens)...")
    migrated_sessions: Dict[int, int] = {}
    # Sessões
    sessions: List[ChatSession] = db_src.query(ChatSession).order_by(ChatSession.created_at.asc()).all()
    for s in sessions:
        mapped_cluster_id = cluster_id_map.get(s.cluster_id)
        if not mapped_cluster_id:
            continue
        existing = db_dst.query(ChatSession).filter(ChatSession.cluster_id == mapped_cluster_id).first()
        if existing:
            migrated_sessions[s.id] = existing.id
            continue
        clone = ChatSession(
            cluster_id=mapped_cluster_id,
            created_at=s.created_at or datetime.utcnow(),
            updated_at=s.updated_at or datetime.utcnow(),
        )
        db_dst.add(clone)
        db_dst.commit()
        db_dst.refresh(clone)
        migrated_sessions[s.id] = clone.id

    # Mensagens
    count_msgs = 0
    msgs: List[ChatMessage] = db_src.query(ChatMessage).order_by(ChatMessage.timestamp.asc()).all()
    for m in msgs:
        mapped_session_id = migrated_sessions.get(m.session_id)
        if not mapped_session_id:
            continue
        clone = ChatMessage(
            session_id=mapped_session_id,
            role=m.role,
            content=m.content,
            timestamp=m.timestamp,
        )
        db_dst.add(clone)
        count_msgs += 1
        if count_msgs % 500 == 0:
            db_dst.commit()
    db_dst.commit()
    print(f"✅ Sessões migradas: {len(migrated_sessions)} | Mensagens migradas: {count_msgs}")
    return count_msgs


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra dados do Postgres local para o Postgres do Heroku")
    parser.add_argument(
        "--source",
        default=os.getenv("SOURCE_DATABASE_URL", "postgresql+psycopg2://postgres_local@localhost:5433/devdb"),
        help="URL do Postgres de origem",
    )
    parser.add_argument(
        "--dest",
        default=os.getenv("DEST_DATABASE_URL", ""),
        help="URL do Postgres de destino (Heroku)",
    )
    parser.add_argument("--include-logs", action="store_true", help="Migrar logs também")
    parser.add_argument("--include-chat", action="store_true", help="Migrar chat (sessões e mensagens)")
    args = parser.parse_args()

    if not args.dest:
        raise SystemExit("Informe --dest com a URL do Postgres do Heroku")

    print("Conectando às bases...")
    db_src, db_dst = create_sessions(args.source, args.dest)
    try:
        # Ordem segura de migração
        cluster_id_map = migrate_clusters(db_src, db_dst)
        migrate_artigos(db_src, db_dst, cluster_id_map)
        migrate_sinteses(db_src, db_dst)
        migrate_configuracoes(db_src, db_dst)
        migrate_cluster_alteracoes(db_src, db_dst, cluster_id_map)
        if args.include_chat:
            migrate_chat(db_src, db_dst, cluster_id_map)
        if args.include_logs:
            migrate_logs(db_src, db_dst)
    finally:
        db_src.close()
        db_dst.close()

    print("🎯 Migração concluída.")


if __name__ == "__main__":
    main()


