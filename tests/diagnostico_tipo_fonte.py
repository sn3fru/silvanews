#!/usr/bin/env python3
"""
Diagnóstico de tipo_fonte (nacional/internacional) para Artigos e Clusters do dia.

Uso:
  python tests/diagnostico_tipo_fonte.py                 # hoje (GMT-3)
  python tests/diagnostico_tipo_fonte.py --day 2025-08-20
  python tests/diagnostico_tipo_fonte.py --check-clusters 10480,10482,10476

Saídas:
  - Contagem de ArtigoBruto por tipo_fonte (nacional/internacional/indefinido)
  - Top jornais de artigos com tipo_fonte indefinido + sugestão de inferência
  - Contagem de ClusterEvento por tipo_fonte e verificações de consistência
  - Inspeção detalhada de clusters específicos (--check-clusters)
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from datetime import datetime
from collections import Counter, defaultdict

from sqlalchemy import func

# Garante imports relativos ao projeto quando executado via `python tests/diagnostico_tipo_fonte.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal, ArtigoBruto, ClusterEvento  # type: ignore
from utils import get_date_brasil_str, inferir_tipo_fonte_por_jornal  # type: ignore


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Diagnóstico de tipo_fonte por dia")
    ap.add_argument("--day", type=str, default=None, help="YYYY-MM-DD (default: hoje GMT-3)")
    ap.add_argument("--max-samples", type=int, default=20, help="Número máximo de amostras para imprimir")
    ap.add_argument("--check-clusters", type=str, default="", help="Lista de IDs de clusters separada por vírgulas")
    return ap.parse_args()


def _fmt(s: Optional[str]) -> str:
    if s is None:
        return ""
    return (s or "").replace("\n", " ").strip()


def diagnosticar_artigos(db, day_str: str, max_samples: int) -> Dict[str, Any]:
    print("\n=== ARTIGOS (por tipo_fonte) ===")
    artigos = (
        db.query(ArtigoBruto)
        .filter(func.date(ArtigoBruto.created_at) == day_str)
        .all()
    )
    total = len(artigos)
    # Normaliza tipo_fonte para contagem
    cont = Counter(((a.tipo_fonte or "").strip().lower()) for a in artigos)
    n_nac = cont.get("nacional", 0)
    n_int = cont.get("internacional", 0)
    n_unk = total - (n_nac + n_int)
    print(f"Total artigos do dia: {total}")
    print(f"  nacional:        {n_nac}")
    print(f"  internacional:   {n_int}")
    print(f"  indefinido/otros:{n_unk}")

    # Raw valores distintos de tipo_fonte (debug)
    valores_raw = Counter((a.tipo_fonte or "") for a in artigos)
    if valores_raw:
        print("\nValores brutos de tipo_fonte em ArtigoBruto (top 10):")
        for v, c in valores_raw.most_common(10):
            print(f"  '{v}': {c}")

    # Sinaliza possíveis internacionais perdidos (heurística por jornal/idioma)
    suspeitos = [
        a for a in artigos
        if (a.tipo_fonte or 'nacional') == 'nacional'
        and any(tok in (_fmt(getattr(a, 'jornal', None)) or _fmt((a.metadados or {}).get('fonte_original') or '')).lower() for tok in ['ft', 'financial times', 'reuters', 'bloomberg', 'wall street journal', 'wsj', 'new york times'])
    ]
    if suspeitos:
        print(f"\nPossíveis internacionais marcados como nacional (amostra até {max_samples}):")
        for a in suspeitos[:max_samples]:
            jornal = _fmt(getattr(a, "jornal", None)) or _fmt((a.metadados or {}).get('fonte_original'))
            sug = inferir_tipo_fonte_por_jornal(jornal)
            print(f"  id={a.id} tipo_fonte={a.tipo_fonte or 'N/A'} jornal='{jornal}' sug='{sug}' titulo='{_fmt(a.titulo_extraido)[:120]}'")

    # Top jornais por classe indefinida
    unk = [a for a in artigos if (a.tipo_fonte or "") not in ("nacional", "internacional")]
    if unk:
        jornais = Counter((_fmt(getattr(a, "jornal", None)) or _fmt((a.metadados or {}).get('fonte_original'))) for a in unk)
        print("\nTop jornais entre indefinidos (até 15):")
        for j, c in jornais.most_common(15):
            sug = inferir_tipo_fonte_por_jornal(j)
            print(f"  {j or 'N/A'}: {c}  -> inferência: {sug}")

        # Amostras
        print(f"\nAmostras de artigos indefinidos (até {max_samples}):")
        for a in unk[:max_samples]:
            jornal = _fmt(getattr(a, "jornal", None)) or _fmt((a.metadados or {}).get('fonte_original'))
            sug = inferir_tipo_fonte_por_jornal(jornal)
            print(f"  id={a.id} tipo_fonte={a.tipo_fonte or 'N/A'} jornal='{jornal}' sug='{sug}' titulo='{_fmt(a.titulo_extraido)[:120]}'")

    return {
        "total": total,
        "nacional": n_nac,
        "internacional": n_int,
        "indefinido": n_unk,
    }


def diagnosticar_clusters(db, day_str: str, max_samples: int, check_ids: List[int]) -> None:
    print("\n=== CLUSTERS (por tipo_fonte) ===")
    q = (
        db.query(ClusterEvento)
        .filter(
            func.date(ClusterEvento.created_at) == day_str,
            ClusterEvento.status == 'ativo'
        )
        .all()
    )
    total = len(q)
    cont = Counter(((c.tipo_fonte or "").strip().lower()) for c in q)
    n_nac = cont.get("nacional", 0)
    n_int = cont.get("internacional", 0)
    n_unk = total - (n_nac + n_int)
    print(f"Total clusters do dia: {total}")
    print(f"  nacional:        {n_nac}")
    print(f"  internacional:   {n_int}")
    print(f"  indefinido/otros:{n_unk}")

    valores_raw = Counter((c.tipo_fonte or "") for c in q)
    if valores_raw:
        print("\nValores brutos de tipo_fonte em ClusterEvento (top 10):")
        for v, c in valores_raw.most_common(10):
            print(f"  '{v}': {c}")

    # Consistência: artigos dentro do cluster com tipo_fonte divergente
    from sqlalchemy.orm import Session
    divergencias = []
    for c in q:
        artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).all()
        tipos = Counter((a.tipo_fonte or "") for a in artigos)
        if c.tipo_fonte and any(tf and tf != c.tipo_fonte for tf in tipos.keys()):
            divergencias.append((c, tipos))

    if divergencias:
        print("\nClusters com tipo_fonte divergente dos artigos:")
        for c, tipos in divergencias[:max_samples]:
            print(f"  cluster_id={c.id} tipo_fonte={c.tipo_fonte} titulo='{_fmt(c.titulo_cluster)[:120]}' artigos_tipos={dict(tipos)}")

    # Inspeção de IDs específicos solicitados
    if check_ids:
        print("\nInspeção de clusters específicos:")
        for cid in check_ids:
            c = db.query(ClusterEvento).filter(ClusterEvento.id == cid).first()
            if not c:
                print(f"  cluster_id={cid} NÃO ENCONTRADO")
                continue
            artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == cid).all()
            print(f"  cluster_id={cid} tipo_fonte={c.tipo_fonte or 'N/A'} titulo='{_fmt(c.titulo_cluster)[:160]}' n_artigos={len(artigos)}")
            # Amostra de artigos e seus jornais
            for a in artigos[:min(max_samples, 10)]:
                jornal = _fmt(getattr(a, "jornal", None)) or _fmt((a.metadados or {}).get('fonte_original'))
                sug = inferir_tipo_fonte_por_jornal(jornal)
                print(f"    artigo_id={a.id} tipo_fonte={a.tipo_fonte or 'N/A'} jornal='{jornal}' sug='{sug}' titulo='{_fmt(a.titulo_extraido)[:120]}'")

        # Se IDs foram checados especificamente, também mostrar distribuição por tipo_fonte dentro deles
        for cid in check_ids:
            c = db.query(ClusterEvento).filter(ClusterEvento.id == cid).first()
            if not c:
                continue
            artigos = db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == cid).all()
            tipos = Counter(((a.tipo_fonte or '').strip().lower()) for a in artigos)
            print(f"  → Distribuição interna cluster {cid}: {dict(tipos)}")


def main() -> None:
    args = parse_args()
    day_str = args.day or get_date_brasil_str()
    check_ids: List[int] = []
    if args.check_clusters:
        for tok in args.check_clusters.split(','):
            tok = tok.strip()
            if not tok:
                continue
            try:
                check_ids.append(int(tok))
            except Exception:
                pass

    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"🧪 Diagnóstico de tipo_fonte — dia {day_str}")
        print("=" * 60)

        _ = diagnosticar_artigos(db, day_str, args.max_samples)
        diagnosticar_clusters(db, day_str, args.max_samples, check_ids)

        print("\n✔️ FIM DO DIAGNÓSTICO")
    finally:
        db.close()


if __name__ == "__main__":
    main()


