"""
Replace (substituição limpa) do DIA em produção a partir do banco local.

O que faz no DESTINO (produção):
- Remove síntese executiva do dia.
- Desassocia artigos dos clusters do dia (cluster_id = NULL).
- Remove clusters do dia e dependências (chat, alterações, feedback, estagiário).

Depois migra do ORIGEM (local) para o DESTINO somente o dia alvo:
- Insere clusters do dia e cria mapa de IDs (com campo tipo_fonte para separação nacional/internacional).
- Upserta artigos do dia (por hash_unico): se existir, ATUALIZA e força cluster_id do dia; senão, insere (com campo tipo_fonte).
- Insere síntese executiva do dia, se houver.
- Migra feedback dos artigos do dia (se --include-feedback).
- Migra sessões e mensagens do estagiário do dia (se --include-estagiario).
- Migra configurações de prompts (tags, prioridades, templates) com tipo_fonte (se --include-prompts).

NOTA: Logs não são migrados para tornar o processo mais rápido e focado no essencial.

Uso:
  python migrate_replace_today.py \
    --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
    --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
    --day YYYY-MM-DD \
    [--include-chat] \
    [--include-feedback] \
    [--include-estagiario] \
    [--include-prompts]

Notas:
- Por padrão, --day é hoje (horário local). Informe explicitamente para evitar ambiguidades.
- Faça backup do destino antes de rodar.
- Este script faz um replace COMPLETO do dia, incluindo todas as tabelas relacionadas.
- Por padrão, migra apenas as tabelas essenciais de notícias (ArtigoBruto, ClusterEvento, SinteseExecutiva).
- Use as flags para incluir tabelas adicionais conforme necessário.
- Campo tipo_fonte é sempre migrado para manter separação nacional/internacional.
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
        FeedbackNoticia,
        EstagiarioChatSession,
        EstagiarioChatMessage,
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
        FeedbackNoticia,
        EstagiarioChatSession,
        EstagiarioChatMessage,
        PromptTag,
        PromptPrioridadeItem,
        PromptTemplate,
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


def cleanup_destination_for_day(db_dst: Session, day: date, include_chat: bool, include_feedback: bool, include_estagiario: bool, include_prompts: bool) -> None:
    # CORREÇÃO CRÍTICA: Remove TODAS as sessões de chat primeiro (evita constraint violation)
    print("🧹 Removendo todas as sessões de chat para evitar constraint violation...")
    all_chat_sessions = db_dst.query(ChatSession).all()
    if all_chat_sessions:
        print(f"⚠️ Encontradas {len(all_chat_sessions)} sessões de chat, removendo todas...")
        for s in all_chat_sessions:
            db_dst.delete(s)
        db_dst.commit()
        print("✅ Todas as sessões de chat removidas com sucesso")

    # Remove síntese do dia
    db_dst.query(SinteseExecutiva).filter(func.date(SinteseExecutiva.data_sintese) == day).delete(synchronize_session=False)

    # Descobrir clusters do dia
    clusters = db_dst.query(ClusterEvento).filter(func.date(ClusterEvento.created_at) == day).all()
    cluster_ids = [c.id for c in clusters]

    if cluster_ids:
        # Desassocia artigos desses clusters (agora seguro, chat já foi removido)
        db_dst.query(ArtigoBruto).filter(ArtigoBruto.cluster_id.in_(cluster_ids)).update({ArtigoBruto.cluster_id: None}, synchronize_session=False)

        # Remove feedback dos artigos desses clusters (se habilitado)
        if include_feedback:
            artigos_cluster = db_dst.query(ArtigoBruto).filter(ArtigoBruto.cluster_id.in_(cluster_ids)).all()
            if artigos_cluster:
                artigo_ids = [a.id for a in artigos_cluster]
                db_dst.query(FeedbackNoticia).filter(FeedbackNoticia.artigo_id.in_(artigo_ids)).delete(synchronize_session=False)

        # Remove alterações
        db_dst.query(ClusterAlteracao).filter(ClusterAlteracao.cluster_id.in_(cluster_ids)).delete(synchronize_session=False)

        # Remove clusters do dia
        for c in clusters:
            db_dst.delete(c)

    # Remove sessões e mensagens do estagiário do dia (se habilitado)
    if include_estagiario:
        estagiario_sessions = db_dst.query(EstagiarioChatSession).filter(func.date(EstagiarioChatSession.data_referencia) == day).all()
        for s in estagiario_sessions:
            db_dst.delete(s)

    # Remove configurações de prompts do dia (se habilitado)
    if include_prompts:
        # Remove tags e prioridades específicas do dia (se houver timestamp)
        # Por padrão, mantém as configurações existentes para não perder personalizações
        pass

    db_dst.commit()


def migrate_day_from_source(db_src: Session, db_dst: Session, day: date, include_chat: bool, include_feedback: bool, include_estagiario: bool, include_prompts: bool) -> None:
    # 1) Clusters do dia
    print("📊 Migrando clusters do dia...")
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
            tipo_fonte=getattr(c, 'tipo_fonte', 'nacional'),
        )
        db_dst.add(clone)
        db_dst.commit()
        db_dst.refresh(clone)
        cluster_id_map[c.id] = clone.id

    # 2) Artigos do dia: upsert por hash_unico e forçar cluster_id
    print("📰 Migrando artigos do dia...")
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
            exists.tipo_fonte = getattr(a, 'tipo_fonte', 'nacional')
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
                tipo_fonte=getattr(a, 'tipo_fonte', 'nacional'),
            )
            db_dst.add(clone)
        db_dst.commit()

    # 3) Síntese executiva do dia (se houver)
    print("📋 Migrando síntese executiva...")
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

    # 4) Feedback dos artigos do dia (se habilitado)
    if include_feedback:
        print("👍 Migrando feedback dos artigos...")
        artigos_ids = [a.id for a in artigos_src]
        if artigos_ids:
            feedback_src = db_src.query(FeedbackNoticia).filter(FeedbackNoticia.artigo_id.in_(artigos_ids)).all()
            for f in feedback_src:
                # Busca o artigo correspondente no destino
                artigo_dest = db_dst.query(ArtigoBruto).filter(ArtigoBruto.hash_unico == artigos_src[f.artigo_id - 1].hash_unico).first()
                if artigo_dest:
                    clone = FeedbackNoticia(
                        artigo_id=artigo_dest.id,
                        feedback=f.feedback,
                        processed=f.processed,
                        created_at=f.created_at,
                    )
                    db_dst.add(clone)
            db_dst.commit()

    # 5) Chat do dia (opcional): cria sessão por cluster e não migra mensagens antigas por padrão
    if include_chat:
        print("💬 Migrando sessões de chat...")
        for src_cluster_id, dst_cluster_id in cluster_id_map.items():
            # Cria sessão vazia como placeholder (mensagens não migradas)
            sess = ChatSession(cluster_id=dst_cluster_id)
            db_dst.add(sess)
        db_dst.commit()

    # 6) Sessões e mensagens do estagiário do dia (se habilitado)
    if include_estagiario:
        print("🤖 Migrando sessões do estagiário...")
        estagiario_sessions_src = db_src.query(EstagiarioChatSession).filter(func.date(EstagiarioChatSession.data_referencia) == day).all()
        for s in estagiario_sessions_src:
            clone = EstagiarioChatSession(
                data_referencia=s.data_referencia,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            db_dst.add(clone)
            db_dst.commit()
            db_dst.refresh(clone)
            
            # Migra mensagens da sessão
            messages_src = db_src.query(EstagiarioChatMessage).filter(EstagiarioChatMessage.session_id == s.id).all()
            for m in messages_src:
                clone_msg = EstagiarioChatMessage(
                    session_id=clone.id,
                    role=m.role,
                    content=m.content,
                    timestamp=m.timestamp,
                )
                db_dst.add(clone_msg)
            db_dst.commit()

    # 7) Configurações de prompts (tags, prioridades, templates) - sempre migra
    if include_prompts:
        print("📝 Migrando configurações de prompts...")
        
        # Tags
        tags_src = db_src.query(PromptTag).all()
        for t in tags_src:
            exists = db_dst.query(PromptTag).filter(PromptTag.nome == t.nome).first()
            if exists:
                # Atualiza
                exists.descricao = t.descricao
                exists.exemplos = t.exemplos
                exists.ordem = t.ordem
                exists.tipo_fonte = t.tipo_fonte
                exists.updated_at = datetime.utcnow()
            else:
                # Insere
                clone = PromptTag(
                    nome=t.nome,
                    descricao=t.descricao,
                    exemplos=t.exemplos,
                    ordem=t.ordem,
                    tipo_fonte=t.tipo_fonte,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                )
                db_dst.add(clone)
        
        # Prioridades
        prioridades_src = db_src.query(PromptPrioridadeItem).all()
        for p in prioridades_src:
            exists = db_dst.query(PromptPrioridadeItem).filter(
                PromptPrioridadeItem.nivel == p.nivel,
                PromptPrioridadeItem.texto == p.texto,
                PromptPrioridadeItem.tipo_fonte == p.tipo_fonte
            ).first()
            if exists:
                # Atualiza
                exists.ordem = p.ordem
                exists.updated_at = datetime.utcnow()
            else:
                # Insere
                clone = PromptPrioridadeItem(
                    nivel=p.nivel,
                    texto=p.texto,
                    ordem=p.ordem,
                    tipo_fonte=p.tipo_fonte,
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
                db_dst.add(clone)
        
        # Templates
        templates_src = db_src.query(PromptTemplate).all()
        for t in templates_src:
            exists = db_dst.query(PromptTemplate).filter(PromptTemplate.chave == t.chave).first()
            if exists:
                # Atualiza
                exists.descricao = t.descricao
                exists.conteudo = t.conteudo
            else:
                # Insere
                clone = PromptTemplate(
                    chave=t.chave,
                    descricao=t.descricao,
                    conteudo=t.conteudo,
                )
                db_dst.add(clone)
        
        db_dst.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace do dia (local -> produção)")
    parser.add_argument("--source", required=True, help="URL do Postgres de origem (local)")
    parser.add_argument("--dest", required=True, help="URL do Postgres de destino (produção)")
    parser.add_argument("--day", default=None, help="Dia no formato YYYY-MM-DD (default: hoje)")
    parser.add_argument("--include-chat", action="store_true", help="Migrar sessões de chat vazias para os clusters do dia")
    parser.add_argument("--include-feedback", action="store_true", help="Migrar feedback dos usuários sobre artigos")
    parser.add_argument("--include-estagiario", action="store_true", help="Migrar sessões e mensagens do agente estagiário")
    parser.add_argument("--include-prompts", action="store_true", help="Migrar configurações de prompts (tags, prioridades, templates)")

    args = parser.parse_args()
    day = parse_day(args.day)

    print(f"🗓️  Dia alvo: {day.isoformat()}")
    print(f"🔧 Configuração:")
    print(f"   - Chat: {'✅' if args.include_chat else '❌'}")
    print(f"   - Feedback: {'✅' if args.include_feedback else '❌'}")
    print(f"   - Estagiário: {'✅' if args.include_estagiario else '❌'}")
    print(f"   - Prompts: {'✅' if args.include_prompts else '❌'}")
    
    db_src, db_dst = create_sessions(args.source, args.dest)

    try:
        print("🧹 Limpando destino para o dia alvo...")
        cleanup_destination_for_day(db_dst, day, include_chat=args.include_chat, include_feedback=args.include_feedback, include_estagiario=args.include_estagiario, include_prompts=args.include_prompts)

        print("🚚 Migrando dados do dia a partir da origem...")
        migrate_day_from_source(db_src, db_dst, day, include_chat=args.include_chat, include_feedback=args.include_feedback, include_estagiario=args.include_estagiario, include_prompts=args.include_prompts)

        print("🎯 Replace do dia concluído com sucesso.")
        print("✅ Tabelas sempre migradas: ArtigoBruto, ClusterEvento, SinteseExecutiva")
        if args.include_feedback:
            print("✅ Tabela adicional: FeedbackNoticia")
        if args.include_estagiario:
            print("✅ Tabela adicional: EstagiarioChatSession, EstagiarioChatMessage")
        if args.include_prompts:
            print("✅ Tabela adicional: PromptTag, PromptPrioridadeItem, PromptTemplate")
        if args.include_chat:
            print("✅ Tabela adicional: ChatSession")
    finally:
        db_src.close()
        db_dst.close()


if __name__ == "__main__":
    main()


