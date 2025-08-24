#!/usr/bin/env python3
"""
Reprocessa um DIA específico (ou hoje por padrão) com os prompts atuais.

Passos:
- Mantém os dados brutos (texto_bruto, metadados)
- Reseta artigos da data para status 'pendente' e limpa campos processados
- Desassocia artigos dos clusters da data
- Remove clusters da data (e artefatos relacionados: chat, alterações, sínteses)
- Executa o pipeline completo de reprocessamento (processar → agrupar → classificar → priorizar)

Uso (Windows CMD):
  python reprocess_today.py                    # Reprocessa hoje
  python reprocess_today.py --day 2025-08-24  # Reprocessa data específica
"""

import argparse
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
    DeepResearchJob,
    SocialResearchJob,
)
from backend.utils import get_date_brasil_str
from process_articles import processar_artigos_pendentes, priorizacao_executiva_final, consolidacao_final_clusters, client


def parse_args():
    ap = argparse.ArgumentParser(description="Reprocessa um dia específico ou hoje")
    ap.add_argument("--day", help="Data no formato YYYY-MM-DD (padrão: hoje)")
    return ap.parse_args()


def resetar_artigos_da_data(db, day_str: str) -> int:
    """Reseta artigos da data para 'pendente' e limpa campos processados, mantendo texto_bruto/metadados."""
    artigos = (
        db.query(ArtigoBruto)
        .filter(func.date(ArtigoBruto.created_at) == day_str)
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


def remover_clusters_da_data(db, day_str: str) -> int:
    """Remove clusters da data e objetos dependentes (chat, alterações, sínteses)."""
    # Sinteses do dia (se existir)
    db.query(SinteseExecutiva).filter(
        func.date(SinteseExecutiva.data_sintese) == day_str
    ).delete(synchronize_session=False)

    clusters = (
        db.query(ClusterEvento)
        .filter(func.date(ClusterEvento.created_at) == day_str)
        .all()
    )

    removidos = 0
    for c in clusters:
        # Remove jobs de pesquisa (deep e social)
        db.query(DeepResearchJob).filter(DeepResearchJob.cluster_id == c.id).delete(synchronize_session=False)
        db.query(SocialResearchJob).filter(SocialResearchJob.cluster_id == c.id).delete(synchronize_session=False)

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


def reprocessar_data(day_str: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        target_day = day_str or get_date_brasil_str()
        print("=" * 60)
        print(f"🔄 Reprocessamento do dia: {target_day}")
        print("=" * 60)

        # 1) Resetar artigos da data
        qtd_resets = resetar_artigos_da_data(db, target_day)
        print(f"🧹 Artigos da data resetados para 'pendente': {qtd_resets}")

        # 2) Remover clusters da data
        qtd_clusters = remover_clusters_da_data(db, target_day)
        print(f"🗑️  Clusters removidos da data: {qtd_clusters}")

        # 3) Rodar pipeline completo com prompts atuais (Etapas 1–3)
        print("🚀 Iniciando reprocessamento (Etapas 1–3)...")
        sucesso = processar_artigos_pendentes(limite=999, day_str=target_day)
        if not sucesso:
            print("❌ Reprocessamento falhou nas Etapas 1–3. Verifique os logs.")
            return

        # 4) Executar Etapa 4 (Priorização Executiva + Consolidação Final)
        print("\n⚙️ Executando Etapa 4: Priorização Executiva + Consolidação Final...")
        db4 = SessionLocal()
        try:
            ok_prio = priorizacao_executiva_final(db4, client)
        finally:
            db4.close()

        db5 = SessionLocal()
        try:
            ok_cons = consolidacao_final_clusters(db5, client, day_str=target_day)
        finally:
            db5.close()

        if ok_prio and ok_cons:
            print("🎉 Reprocessamento concluído com sucesso (Etapas 1–4)!")
        else:
            print("❌ Reprocessamento concluiu com falhas na Etapa 4. Verifique os logs.")

    finally:
        db.close()


def main():
    args = parse_args()
    reprocessar_data(args.day)


if __name__ == "__main__":
    main()