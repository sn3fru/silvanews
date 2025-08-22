import os
from typing import List, Optional

import numpy as np


class Embedder:
    """
    Abstração para provedores de embeddings. Implementação padrão usa OpenAI
    via variável de ambiente OPENAI_API_KEY, modelo text-embedding-3-small.
    Fallback: embedding determinístico simples (hash) para ambientes sem chave.
    """

    def __init__(self, provider: str = "openai", model: str = "text-embedding-3-small") -> None:
        self.provider = provider
        self.model = model
        self._client = None
        self._available = False
        if provider == "openai":
            try:
                import openai  # type: ignore
                api_key = os.getenv("OPENAI_API_KEY")
                if api_key:
                    self._client = openai.OpenAI(api_key=api_key)  # type: ignore
                    self._available = True
            except Exception:
                self._client = None
                self._available = False

    def is_available(self) -> bool:
        return self._available

    def embed_text(self, text: str) -> np.ndarray:
        if self.provider == "openai" and self._available:
            try:
                resp = self._client.embeddings.create(input=[text], model=self.model)  # type: ignore
                vec: List[float] = resp.data[0].embedding  # type: ignore
                return np.array(vec, dtype=np.float32)
            except Exception:
                pass
        # Fallback determinístico, mesma ideia do backend.processing
        import hashlib

        h = hashlib.md5(text.encode("utf-8")).digest()
        seed = int.from_bytes(h[:4], "big")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(384).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


_DEFAULT_EMBEDDER: Optional[Embedder] = None


def get_default_embedder() -> Embedder:
    global _DEFAULT_EMBEDDER
    if _DEFAULT_EMBEDDER is None:
        _DEFAULT_EMBEDDER = Embedder()
    return _DEFAULT_EMBEDDER


