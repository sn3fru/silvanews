#!/usr/bin/env python3
"""
Reprocessar incremental de hoje (Etapa 2 → 3 → 4) para itens marcados como 'pronto_agrupar' após reversão.

Uso:
  python reprocess_incremental_today.py
"""

from datetime import date
from sqlalchemy import func

from process_articles import (
    agrupar_noticias_incremental,
    classificar_e_resumir_cluster,
    priorizacao_executiva_final,
    consolidacao_final_clusters,
    client,
)
from backend.database import SessionLocal, ClusterEvento


def main() -> None:
    db = SessionLocal()
    try:
        print('→ Agrupando incremental...')
        agrupar_noticias_incremental(db, client)

        hoje = date.today()
        clusters_sem_resumo = db.query(ClusterEvento).filter(
            ClusterEvento.status == 'ativo',
            func.date(ClusterEvento.created_at) == hoje,
            ClusterEvento.resumo_cluster.is_(None)
        ).all()
        print(f'→ Classificando/sumarizando {len(clusters_sem_resumo)} clusters...')
        ok = 0
        for c in clusters_sem_resumo:
            if classificar_e_resumir_cluster(db, c.id, client, debug=False):
                ok += 1
        print(f'→ Resumos OK: {ok}/{len(clusters_sem_resumo)}')

        print('→ Etapa 4: Priorização...')
        priorizacao_executiva_final(SessionLocal(), client, debug=True)
        print('→ Etapa 4: Consolidação...')
        consolidacao_final_clusters(SessionLocal(), client, debug=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()


