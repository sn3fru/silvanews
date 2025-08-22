from typing import List, Dict, Any

import numpy as np

try:
    from backend.database import SessionLocal, ArtigoBruto, SemanticEmbedding
except Exception:
    from btg_alphafeed.backend.database import SessionLocal, ArtigoBruto, SemanticEmbedding  # type: ignore


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return -1.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return -1.0
    return float(np.dot(a, b) / denom)


def semantic_search(query_vector: np.ndarray, model: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Busca semântica simples em memória usando os embeddings salvos.
    Mantém compatibilidade sem pgvector. Para grandes bases, migrar para vetor no Postgres.
    """
    db = SessionLocal()
    try:
        rows = db.query(SemanticEmbedding).filter(SemanticEmbedding.model == model).all()
        candidates = []
        for r in rows:
            vec = np.frombuffer(r.vector_bytes, dtype="float32")
            sim = _cosine_similarity(query_vector, vec)
            if sim >= 0:
                candidates.append((sim, r.artigo_id))
        candidates.sort(reverse=True, key=lambda x: x[0])
        top = candidates[: max(1, top_k)]
        if not top:
            return []
        artigo_ids = [aid for _, aid in top]
        artigos = db.query(ArtigoBruto).filter(ArtigoBruto.id.in_(artigo_ids)).all()
        by_id = {a.id: a for a in artigos}
        results: List[Dict[str, Any]] = []
        for sim, aid in top:
            a = by_id.get(aid)
            if not a:
                continue
            results.append(
                {
                    "id": a.id,
                    "titulo": a.titulo_extraido or "Sem título",
                    "texto": a.texto_processado or a.texto_bruto,
                    "data": a.data_publicacao,
                    "sim": sim,
                }
            )
        return results
    finally:
        try:
            db.close()
        except Exception:
            pass


