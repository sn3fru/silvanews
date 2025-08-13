#!/usr/bin/env python3
"""
Reprocessa APENAS o dia de hoje com os prompts atuais.

Passos:
- Mantém os dados brutos (texto_bruto, metadados)
- Reseta artigos de hoje para status 'pendente' e limpa campos processados
- Desassocia artigos dos clusters de hoje
- Remove clusters gerados hoje (e artefatos relacionados: chat, alterações, sínteses)
- Executa o pipeline completo de reprocessamento (processar → agrupar → classificar → priorizar)

Uso (Windows CMD):
  python reprocess_today.py
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func

from backend.database import (
    SessionLocal,
    ArtigoBruto,
    ClusterEvento,
    ChatSession,
    ChatMessage,
    ClusterAlteracao,
    SinteseExecutiva,
)
from backend.utils import get_date_brasil_str


def resetar_artigos_hoje(db) -> int:
    """Reseta artigos criados hoje para 'pendente' e limpa campos processados, mantendo texto_bruto/metadados."""
    hoje_str = get_date_brasil_str()
    artigos = (
        db.query(ArtigoBruto)
        .filter(func.date(ArtigoBruto.created_at) == hoje_str)
        .all()
    )

    count = 0
    for a in artigos:
        a.status = 'pendente'
        a.processed_at = None
        # Mantém texto_bruto e metadados; limpa processados
        a.titulo_extraido = None
        a.texto_processado = None
        a.jornal = None
        a.autor = None
        a.pagina = None
        a.data_publicacao = None
        a.categoria = None
        a.tag = 'PENDING'
        a.prioridade = 'PENDING'
        a.relevance_score = None
        a.relevance_reason = None
        a.embedding = None
        a.cluster_id = None
        count += 1

    db.commit()
    return count


def remover_clusters_hoje(db) -> int:
    """Remove clusters criados hoje e objetos dependentes (chat, alterações, sínteses)."""
    hoje_str = get_date_brasil_str()

    # Sinteses do dia (se existir)
    db.query(SinteseExecutiva).filter(
        func.date(SinteseExecutiva.data_sintese) == hoje_str
    ).delete(synchronize_session=False)

    clusters = (
        db.query(ClusterEvento)
        .filter(func.date(ClusterEvento.created_at) == hoje_str)
        .all()
    )

    removidos = 0
    for c in clusters:
        # Remove sessões de chat (e mensagens via cascade do ChatSession)
        sessions = db.query(ChatSession).filter(ChatSession.cluster_id == c.id).all()
        for s in sessions:
            db.delete(s)

        # Remove alterações do cluster
        db.query(ClusterAlteracao).filter(ClusterAlteracao.cluster_id == c.id).delete(
            synchronize_session=False
        )

        # Desassocia artigos (defensivo; já foi feito em reset de artigos)
        db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).update(
            {ArtigoBruto.cluster_id: None}, synchronize_session=False
        )

        # Remove cluster
        db.delete(c)
        removidos += 1

    db.commit()
    return removidos


def reprocessar_hoje() -> None:
    db = SessionLocal()
    try:
        hoje_str = get_date_brasil_str()
        print("=" * 60)
        print(f"🔄 Reprocessamento do dia: {hoje_str}")
        print("=" * 60)

        # 1) Resetar artigos do dia
        qtd_resets = resetar_artigos_hoje(db)
        print(f"🧹 Artigos do dia resetados para 'pendente': {qtd_resets}")

        # 2) Remover clusters do dia
        qtd_clusters = remover_clusters_hoje(db)
        print(f"🗑️  Clusters removidos do dia: {qtd_clusters}")

        # 3) Rodar pipeline completo com prompts atuais
        print("🚀 Iniciando reprocessamento com prompts atuais...")
        # Import tardio para carregar .env e configurar Gemini conforme process_articles.py
        from process_articles import processar_artigos_pendentes

        sucesso = processar_artigos_pendentes(limite=999)
        if sucesso:
            print("🎉 Reprocessamento concluído com sucesso!")
        else:
            print("❌ Reprocessamento falhou. Verifique os logs acima.")

    finally:
        db.close()


if __name__ == "__main__":
    reprocessar_hoje()