from .embedder import Embedder, get_default_embedder
from .store import upsert_embedding_for_artigo, fetch_all_embeddings
from .search import semantic_search

__all__ = [
    "Embedder",
    "get_default_embedder",
    "upsert_embedding_for_artigo",
    "fetch_all_embeddings",
    "semantic_search",
]


