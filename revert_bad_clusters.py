#!/usr/bin/env python3
"""
Utilitário: Reverter clusters problemáticos do dia (mover artigos para pronto_agrupar e arquivar clusters).

Uso (exemplos - Windows CMD):
  - Reverter clusters com títulos genéricos ("Notícia sem título") de hoje:
      python revert_bad_clusters.py

  - Reverter clusters específicos por ID (separados por vírgula):
      python revert_bad_clusters.py --ids 8349,8350

Após reverter, rode o incremental novamente (ver script: reprocess_incremental_today.py).
"""

import argparse
from datetime import date
from typing import List
from sqlalchemy import func

try:
    from backend.database import SessionLocal, ClusterEvento, ArtigoBruto
except Exception:
    from btg_alphafeed.backend.database import SessionLocal, ClusterEvento, ArtigoBruto  # type: ignore

try:
    from backend.crud import soft_delete_cluster
except Exception:
    from btg_alphafeed.backend.crud import soft_delete_cluster  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reverter clusters problemáticos do dia")
    parser.add_argument(
        "--ids",
        type=str,
        default="",
        help="Lista de IDs de clusters a reverter (ex.: 8349,8350). Se vazio, usa seleção automática por título genérico.")
    return parser.parse_args()


def selecionar_clusters(db, ids: List[int]):
    hoje = date.today()
    q = db.query(ClusterEvento).filter(
        ClusterEvento.status == 'ativo',
        func.date(ClusterEvento.created_at) == hoje,
    )
    if ids:
        return q.filter(ClusterEvento.id.in_(ids)).all()
    # Seleção automática por títulos genéricos
    return q.filter(
        (ClusterEvento.titulo_cluster.ilike('Notícia sem título%')) |
        (ClusterEvento.titulo_cluster.ilike('Notícias sem título%')) |
        (ClusterEvento.titulo_cluster.ilike('Sem título%'))
    ).all()


def main() -> None:
    args = parse_args()
    ids = []
    if args.ids:
        try:
            ids = [int(x.strip()) for x in args.ids.split(',') if x.strip()]
        except Exception:
            print("⚠️ IDs inválidos em --ids; usando seleção automática por título genérico.")
            ids = []

    db = SessionLocal()
    try:
        clusters = selecionar_clusters(db, ids)
        print(f"Clusters selecionados: {[c.id for c in clusters]}")
        revertidos = 0
        for c in clusters:
            artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).all()
            for a in artigos:
                a.cluster_id = None
                a.status = 'pronto_agrupar'
            db.commit()
            soft_delete_cluster(db, c.id, motivo='reversão pós-falha incremental')
            revertidos += 1
        print(f"✅ Clusters revertidos: {revertidos}")
    finally:
        db.close()


if __name__ == "__main__":
    main()


