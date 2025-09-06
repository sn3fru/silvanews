#!/usr/bin/env python3
"""
Ajusta tipo_fonte dos artigos e clusters com escopo configurável.

Regras para artigos:
- Se metadados.tipo_fonte_detectado existir → usa-o diretamente
- Senão, se metadados.tipo_arquivo == 'pdf' ou (url_original vazio) → 'brasil_fisico'
- Senão, se url_original não vazio → 'brasil_online'
- Mantém 'internacional' intocado. Artigos já 'brasil_fisico'/'brasil_online' não são alterados.

Regras para clusters:
- Se qualquer artigo do cluster for 'internacional' → cluster = 'internacional'
- Senão, se houver qualquer 'brasil_fisico' → cluster = 'brasil_fisico'
- Caso contrário → 'brasil_online'

Uso:
  conda activate pymc2
  # somente hoje (padrão)
  python fix_tipo_fonte_today.py
  # um dia específico
  python fix_tipo_fonte_today.py --day 2025-09-01
  # desde uma data (inclui)
  python fix_tipo_fonte_today.py --since 2025-08-01
  # todo o histórico
  python fix_tipo_fonte_today.py --all
  # execução em lotes maiores/menores
  python fix_tipo_fonte_today.py --batch-size 2000
  # dry-run para ver contagens
  python fix_tipo_fonte_today.py --dry-run
"""

import sys
from pathlib import Path

# Garante imports relativos
backend_dir = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from sqlalchemy import func

import argparse
from datetime import datetime, date
from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
from backend.utils import get_date_brasil_str


def normalizar_tipo_artigo(art: ArtigoBruto) -> str:
    try:
        # Respeita internacional
        tipo_atual = getattr(art, 'tipo_fonte', None)
        if tipo_atual == 'internacional':
            return 'internacional'

        metadados = art.metadados or {}
        tipo_detectado = metadados.get('tipo_fonte_detectado')
        tipo_arquivo = (metadados.get('tipo_arquivo') or '').strip().lower()
        url = (art.url_original or '').strip()

        if tipo_detectado in ('brasil_fisico', 'brasil_online', 'internacional'):
            return tipo_detectado

        # Heurística simples
        if tipo_arquivo == 'pdf' or not url:
            return 'brasil_fisico'
        return 'brasil_online'
    except Exception:
        # Fallback seguro
        return 'brasil_fisico'


def recalcular_tipo_cluster(sess: Session, cluster: ClusterEvento) -> str:
    artigos = sess.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == cluster.id).all()
    tipos = [(getattr(a, 'tipo_fonte', None) or '').strip() for a in artigos]
    if any(t == 'internacional' for t in tipos):
        return 'internacional'
    if any(t == 'brasil_fisico' for t in tipos):
        return 'brasil_fisico'
    return 'brasil_online'


def parse_args():
    p = argparse.ArgumentParser(description="Ajusta tipo_fonte de artigos/clusters")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--day", type=str, help="Corrige apenas o dia (YYYY-MM-DD)")
    scope.add_argument("--since", type=str, help="Corrige desde a data (YYYY-MM-DD)")
    scope.add_argument("--all", action="store_true", help="Corrige todo o histórico")
    p.add_argument("--batch-size", type=int, default=2000, help="Tamanho do lote para commits")
    p.add_argument("--dry-run", action="store_true", help="Apenas conta, não grava")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    filtro_texto = "(hoje)"
    filtro_day = None
    filtro_since = None
    if args.day:
        filtro_day = args.day
        filtro_texto = f"(dia {filtro_day})"
    elif args.since:
        filtro_since = args.since
        filtro_texto = f"(desde {filtro_since})"
    elif args.all:
        filtro_texto = "(todo o histórico)"
    else:
        filtro_day = get_date_brasil_str()
        filtro_texto = f"(hoje {filtro_day})"

    print(f"🔧 Ajustando tipo_fonte {filtro_texto}...")

    db = SessionLocal()
    try:
        # Seleção de artigos conforme escopo
        q_art = db.query(ArtigoBruto)
        if filtro_day:
            q_art = q_art.filter(func.date(ArtigoBruto.created_at) == filtro_day)
        elif filtro_since:
            # created_at >= since 00:00
            dt = datetime.fromisoformat(filtro_since)
            q_art = q_art.filter(ArtigoBruto.created_at >= dt)
        # else: --all (sem filtro)

        atualizados = mantidos = 0
        processed = 0
        for art in q_art.yield_per(args.batch_size):
            novo = normalizar_tipo_artigo(art)
            antigo = getattr(art, 'tipo_fonte', None)
            if antigo != novo:
                try:
                    art.tipo_fonte = novo
                    atualizados += 1
                except Exception:
                    mantidos += 1
            else:
                mantidos += 1
            processed += 1
            if not args.dry_run and (processed % args.batch_size == 0):
                db.commit()
        if not args.dry_run:
            db.commit()
        print(f"📰 Artigos processados: {processed} | atualizados: {atualizados} | mantidos: {mantidos}")

        # Seleção de clusters conforme escopo
        q_clu = db.query(ClusterEvento).filter(ClusterEvento.status == 'ativo')
        if filtro_day:
            q_clu = q_clu.filter(func.date(ClusterEvento.created_at) == filtro_day)
        elif filtro_since:
            dt = datetime.fromisoformat(filtro_since)
            q_clu = q_clu.filter(ClusterEvento.created_at >= dt)

        c_atualizados = c_mantidos = 0
        c_processed = 0
        for c in q_clu.yield_per(args.batch_size):
            novo = recalcular_tipo_cluster(db, c)
            antigo = getattr(c, 'tipo_fonte', None)
            if antigo != novo:
                try:
                    c.tipo_fonte = novo
                    c_atualizados += 1
                except Exception:
                    c_mantidos += 1
            else:
                c_mantidos += 1
            c_processed += 1
            if not args.dry_run and (c_processed % args.batch_size == 0):
                db.commit()
        if not args.dry_run:
            db.commit()
        print(f"📁 Clusters processados: {c_processed} | atualizados: {c_atualizados} | mantidos: {c_mantidos}")

        print("✅ Concluído. Recarregue o frontend e, se necessário, rode a Etapa 2 novamente.")
    except Exception as e:
        db.rollback()
        print(f"❌ Erro durante ajuste: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()


