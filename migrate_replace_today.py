"""
Replace (substituição limpa) do DIA em produção a partir do banco local.

O que faz no DESTINO (produção):
- Remove síntese executiva do dia.
- Desassocia artigos dos clusters do dia (cluster_id = NULL).
- Remove clusters do dia e dependências (chat, alterações).

Depois migra do ORIGEM (local) para o DESTINO somente o dia alvo:
- Insere clusters do dia e cria mapa de IDs.
- Upserta artigos do dia (por hash_unico): se existir, ATUALIZA e força cluster_id do dia; senão, insere.
- Insere síntese executiva do dia, se houver.

Uso:
  python migrate_replace_today.py \
    --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
    --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
    --day YYYY-MM-DD \
    [--include-chat]

Notas:
- Por padrão, --day é hoje (horário local). Informe explicitamente para evitar ambiguidades.
- Faça backup do destino antes de rodar.
"""

# python migrate_replace_today.py --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" --dest "postgres://u71uif3ajf4qqh:pbfa5924f245d80b107c9fb38d5496afc0c1372a3f163959faa933e5b9f7c47d6@c3v5n5ajfopshl.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/daoetg9ahbmcff" --day "2025-08-13" --include-chat


from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime, date
from typing import Dict, Optional, Tuple, List

from sqlalchemy import create_engine, func, and_, or_
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
    )


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


def parse_day(day_str: Optional[str]) -> date:
    if not day_str:
        return datetime.now().date()
    return datetime.strptime(day_str, "%Y-%m-%d").date()


def cleanup_destination_for_day(db_dst: Session, day: date, include_chat: bool) -> None:
    # Remove síntese do dia
    db_dst.query(SinteseExecutiva).filter(func.date(SinteseExecutiva.data_sintese) == day).delete(synchronize_session=False)

    # Descobrir clusters do dia
    clusters = db_dst.query(ClusterEvento).filter(func.date(ClusterEvento.created_at) == day).all()
    cluster_ids = [c.id for c in clusters]

    if cluster_ids:
        # Desassocia artigos desses clusters
        db_dst.query(ArtigoBruto).filter(ArtigoBruto.cluster_id.in_(cluster_ids)).update({ArtigoBruto.cluster_id: None}, synchronize_session=False)

        # Remove alterações
        db_dst.query(ClusterAlteracao).filter(ClusterAlteracao.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)

        # Remove chat (se quiser manter histórico, não use --include-chat ao migrar de volta)
        sessions = db_dst.query(ChatSession).filter(ChatSession.cluster_id.in_(cluster_ids)).all()
        for s in sessions:
            db_dst.delete(s)

        # Remove clusters do dia
        for c in clusters:
            db_dst.delete(c)

    db_dst.commit()


def migrate_day_from_source(db_src: Session, db_dst: Session, day: date, include_chat: bool) -> None:
    # 1) Clusters do dia
    clusters_src = db_src.query(ClusterEvento).filter(func.date(ClusterEvento.created_at) == day).order_by(ClusterEvento.created_at.asc()).all()
    cluster_id_map: Dict[int, int] = {}
    for c in clusters_src:
        clone = ClusterEvento(
            titulo_cluster=c.titulo_cluster,
            resumo_cluster=c.resumo_cluster,
            tag=c.tag,
            prioridade=c.prioridade,
            embedding_medio=c.embedding_medio,
            created_at=c.created_at,
            updated_at=c.updated_at,
            status=c.status or "ativo",
            total_artigos=c.total_artigos or 0,
            ultima_atualizacao=c.ultima_atualizacao or c.created_at,
        )
        db_dst.add(clone)
        db_dst.commit()
        db_dst.refresh(clone)
        cluster_id_map[c.id] = clone.id

    # 2) Artigos do dia: upsert por hash_unico e forçar cluster_id
    artigos_src = db_src.query(ArtigoBruto).filter(func.date(ArtigoBruto.created_at) == day).order_by(ArtigoBruto.created_at.asc()).all()
    for a in artigos_src:
        exists = db_dst.query(ArtigoBruto).filter(ArtigoBruto.hash_unico == a.hash_unico).first()
        target_cluster_id = cluster_id_map.get(a.cluster_id) if a.cluster_id else None
        if exists:
            # Atualiza campos e força cluster_id
            exists.texto_bruto = a.texto_bruto
            exists.url_original = a.url_original
            exists.fonte_coleta = a.fonte_coleta
            exists.metadados = a.metadados or {}
            exists.created_at = a.created_at
            exists.processed_at = a.processed_at
            exists.status = a.status or exists.status
            exists.titulo_extraido = a.titulo_extraido
            exists.texto_processado = a.texto_processado
            exists.jornal = a.jornal
            exists.autor = a.autor
            exists.pagina = a.pagina
            exists.data_publicacao = a.data_publicacao
            exists.categoria = a.categoria
            exists.tag = a.tag
            exists.prioridade = a.prioridade
            exists.relevance_score = a.relevance_score
            exists.relevance_reason = a.relevance_reason
            exists.embedding = a.embedding
            exists.cluster_id = target_cluster_id
        else:
            clone = ArtigoBruto(
                hash_unico=a.hash_unico,
                texto_bruto=a.texto_bruto,
                url_original=a.url_original,
                fonte_coleta=a.fonte_coleta,
                metadados=a.metadados or {},
                created_at=a.created_at,
                processed_at=a.processed_at,
                status=a.status or "pendente",
                titulo_extraido=a.titulo_extraido,
                texto_processado=a.texto_processado,
                jornal=a.jornal,
                autor=a.autor,
                pagina=a.pagina,
                data_publicacao=a.data_publicacao,
                categoria=a.categoria,
                tag=a.tag,
                prioridade=a.prioridade,
                relevance_score=a.relevance_score,
                relevance_reason=a.relevance_reason,
                embedding=a.embedding,
                cluster_id=target_cluster_id,
            )
            db_dst.add(clone)
        db_dst.commit()

    # 3) Síntese executiva do dia (se houver)
    s = db_src.query(SinteseExecutiva).filter(func.date(SinteseExecutiva.data_sintese) == day).first()
    if s:
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
        db_dst.commit()

    # 4) Chat do dia (opcional): cria sessão por cluster e não migra mensagens antigas por padrão
    if include_chat:
        for src_cluster_id, dst_cluster_id in cluster_id_map.items():
            # Cria sessão vazia como placeholder (mensagens não migradas)
            sess = ChatSession(cluster_id=dst_cluster_id)
            db_dst.add(sess)
        db_dst.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace do dia (local -> produção)")
    parser.add_argument("--source", required=True, help="URL do Postgres de origem (local)")
    parser.add_argument("--dest", required=True, help="URL do Postgres de destino (produção)")
    parser.add_argument("--day", default=None, help="Dia no formato YYYY-MM-DD (default: hoje)")
    parser.add_argument("--include-chat", action="store_true", help="Migrar sessões de chat vazias para os clusters do dia")

    args = parser.parse_args()
    day = parse_day(args.day)

    print(f"🗓️  Dia alvo: {day.isoformat()}")
    db_src, db_dst = create_sessions(args.source, args.dest)

    try:
        print("🧹 Limpando destino para o dia alvo...")
        cleanup_destination_for_day(db_dst, day, include_chat=True)

        print("🚚 Migrando dados do dia a partir da origem...")
        migrate_day_from_source(db_src, db_dst, day, include_chat=args.include_chat)

        print("🎯 Replace do dia concluído com sucesso.")
    finally:
        db_src.close()
        db_dst.close()


if __name__ == "__main__":
    main()


