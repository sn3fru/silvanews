#!/usr/bin/env python3
"""
Backfill de tipo_fonte para um dia específico.

O que faz:
- Re-infere tipo_fonte de ArtigoBruto do dia a partir do 'jornal'/'fonte_original'
- Atualiza tipo_fonte dos ClusterEvento do dia pela maioria dos artigos associados

Uso:
  python tests/backfill_tipo_fonte.py --day 2025-08-20 --apply

Por padrão roda em modo dry-run (não aplica). Use --apply para gravar no banco.
"""

import argparse
import sys
from pathlib import Path
from collections import Counter
from typing import Optional

from sqlalchemy import func

# Ajusta sys.path para importar backend/*
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal, ArtigoBruto, ClusterEvento  # type: ignore
from utils import inferir_tipo_fonte_por_jornal  # type: ignore


def _fmt(s: Optional[str]) -> str:
    return (s or "").replace("\n", " ").strip()


def parse_args():
    ap = argparse.ArgumentParser(description="Backfill de tipo_fonte para artigos e clusters do dia")
    ap.add_argument("--day", required=True, help="YYYY-MM-DD (data a corrigir)")
    ap.add_argument("--apply", action="store_true", help="Aplica as alterações no banco (default: dry-run)")
    ap.add_argument("--max", type=int, default=50, help="Máximo de linhas de log por seção")
    return ap.parse_args()


def corrigir_artigos(db, day_str: str, apply: bool, max_log: int) -> int:
    # Artigos criados no dia
    artigos_dia = (
        db.query(ArtigoBruto)
        .filter(func.date(ArtigoBruto.created_at) == day_str)
        .all()
    )
    # Artigos ligados a clusters criados no dia (mesmo que o artigo seja de outro dia)
    clusters_ids = [c.id for c in db.query(ClusterEvento).filter(func.date(ClusterEvento.created_at) == day_str).all()]
    artigos_por_cluster = []
    if clusters_ids:
        artigos_por_cluster = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id.in_(clusters_ids)).all()
    # Unifica conjuntos
    artigos_map = {}
    for a in artigos_dia:
        artigos_map[a.id] = a
    for a in artigos_por_cluster:
        artigos_map[a.id] = a
    artigos = list(artigos_map.values())
    alterados = 0
    logs = 0
    for a in artigos:
        # jornal de preferência: campo estruturado; fallback para metadados
        jornal = _fmt(getattr(a, "jornal", None)) or _fmt((a.metadados or {}).get('jornal')) or _fmt((a.metadados or {}).get('fonte_original'))
        novo_tf = inferir_tipo_fonte_por_jornal(jornal) if jornal else 'nacional'
        novo_tf = 'internacional' if novo_tf == 'internacional' else 'nacional'
        atual = (a.tipo_fonte or 'nacional').strip().lower()
        if novo_tf != atual:
            if logs < max_log:
                print(f"  artigo_id={a.id} {atual} -> {novo_tf} | jornal='{jornal}' | titulo='{_fmt(a.titulo_extraido)[:120]}'")
                logs += 1
            if apply:
                a.tipo_fonte = novo_tf
                alterados += 1
    if apply:
        db.commit()
    return alterados


def corrigir_clusters(db, day_str: str, apply: bool, max_log: int) -> int:
    clusters = (
        db.query(ClusterEvento)
        .filter(
            func.date(ClusterEvento.created_at) == day_str,
            ClusterEvento.status == 'ativo'
        )
        .all()
    )
    alterados = 0
    logs = 0
    for c in clusters:
        artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).all()
        tipos = Counter(((a.tipo_fonte or 'nacional').strip().lower()) for a in artigos)
        # Decide por maioria; empate mantém o atual
        novo_tf = c.tipo_fonte or 'nacional'
        if tipos.get('internacional', 0) > tipos.get('nacional', 0):
            novo_tf = 'internacional'
        else:
            novo_tf = 'nacional'
        atual = (c.tipo_fonte or 'nacional').strip().lower()
        if novo_tf != atual:
            if logs < max_log:
                print(f"  cluster_id={c.id} {atual} -> {novo_tf} | titulo='{_fmt(c.titulo_cluster)[:120]}' | dist={dict(tipos)}")
                logs += 1
            if apply:
                c.tipo_fonte = novo_tf
                alterados += 1
    if apply:
        db.commit()
    return alterados


def main():
    args = parse_args()
    day_str = args.day
    apply = args.apply
    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"🛠️  Backfill tipo_fonte — dia {day_str} ({'APLICANDO' if apply else 'dry-run'})")
        print("=" * 60)

        print("\n➡️  Corrigindo artigos...")
        n_art = corrigir_artigos(db, day_str, apply, args.max)
        print(f"✔️ Artigos alterados: {n_art}{'' if apply else ' (previsto)'}")

        print("\n➡️  Corrigindo clusters por maioria dos artigos...")
        n_cls = corrigir_clusters(db, day_str, apply, args.max)
        print(f"✔️ Clusters alterados: {n_cls}{'' if apply else ' (previsto)'}")

        print("\n✅ FIM")
    finally:
        db.close()


if __name__ == "__main__":
    main()


