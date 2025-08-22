from typing import List, Optional, Tuple

import numpy as np

try:
    from backend.database import SessionLocal, SemanticEmbedding, ArtigoBruto
except Exception:
    from btg_alphafeed.backend.database import SessionLocal, SemanticEmbedding, ArtigoBruto  # type: ignore


def upsert_embedding_for_artigo(
    artigo_id: int,
    vector: np.ndarray,
    provider: str,
    model: str,
) -> bool:
    db = SessionLocal()
    try:
        existing = (
            db.query(SemanticEmbedding)
            .filter(SemanticEmbedding.artigo_id == artigo_id, SemanticEmbedding.model == model)
            .first()
        )
        vec_bytes = vector.astype("float32").tobytes()
        if existing:
            existing.vector_bytes = vec_bytes
            existing.dimension = int(vector.shape[0])
            existing.provider = provider
            db.commit()
            return True
        row = SemanticEmbedding(
            artigo_id=artigo_id,
            vector_bytes=vec_bytes,
            dimension=int(vector.shape[0]),
            provider=provider,
            model=model,
        )
        db.add(row)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


def fetch_all_embeddings(model: str) -> List[Tuple[int, np.ndarray]]:
    """Retorna lista (artigo_id, vector) para um modelo específico."""
    db = SessionLocal()
    try:
        rows = db.query(SemanticEmbedding).filter(SemanticEmbedding.model == model).all()
        out: List[Tuple[int, np.ndarray]] = []
        for r in rows:
            try:
                vec = np.frombuffer(r.vector_bytes, dtype="float32")
                out.append((r.artigo_id, vec))
            except Exception:
                continue
        return out
    finally:
        try:
            db.close()
        except Exception:
            pass


