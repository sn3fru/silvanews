#!/usr/bin/env python3
"""
Backfill de embeddings semânticos para artigos existentes.

Uso:
  conda activate pymc2
  python -m btg_alphafeed.semantic_search.backfill_embeddings --model text-embedding-3-small --limit 500
"""

import argparse
from typing import Optional

import numpy as np

try:
    from backend.database import SessionLocal, ArtigoBruto
except Exception:
    from btg_alphafeed.backend.database import SessionLocal, ArtigoBruto  # type: ignore

from .embedder import get_default_embedder
from .store import upsert_embedding_for_artigo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    embedder = get_default_embedder()
    model = args.model
    provider = embedder.provider

    db = SessionLocal()
    try:
        # Busca artigos mais recentes que ainda não possuem embedding para o modelo
        # Simples: processa por created_at desc; o store faz upsert
        artigos = (
            db.query(ArtigoBruto)
            .order_by(ArtigoBruto.created_at.desc())
            .limit(args.limit)
            .all()
        )
        total, ok = 0, 0
        for a in artigos:
            total += 1
            titulo = a.titulo_extraido or ""
            texto = a.texto_processado or a.texto_bruto or ""
            blob = f"{titulo}. {texto}"
            vec = embedder.embed_text(blob)
            if isinstance(vec, np.ndarray) and vec.size > 0:
                if upsert_embedding_for_artigo(a.id, vec, provider, model):
                    ok += 1
        print(f"Embeddings processados: {ok}/{total} (model={model}, provider={provider})")
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()


