"""
Embedding utilities for training scripts.

We avoid coupling training to backend runtime settings (OpenAI keys, etc.).
Training scripts can choose a local sentence-transformers model explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class EmbeddingBackend:
    model_name: str
    dimension: int
    embed_text: Callable[[str], List[float]]


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def load_sentence_transformer_backend(model_name: str) -> EmbeddingBackend:
    """
    Load a local sentence-transformers model.

    Notes:
    - You must ensure the backend app uses the same embedding model + dimension
      when querying the built FAISS index.
    """
    from sentence_transformers import SentenceTransformer

    device = "cuda" if _has_cuda() else "cpu"
    model = SentenceTransformer(model_name, device=device)
    dim = int(model.get_sentence_embedding_dimension())

    def embed_text(text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * dim
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype("float32").tolist()

    return EmbeddingBackend(model_name=model_name, dimension=dim, embed_text=embed_text)


def load_hashing_backend(*, dimension: int = 1536) -> EmbeddingBackend:
    """
    Offline-safe embedding backend using feature hashing (no model downloads).

    This is NOT as semantically strong as transformer embeddings, but it:
    - works without internet / model weights
    - provides deterministic vectors for FAISS indexing
    - is sufficient to validate the end-to-end GraphRAG pipeline offline
    """
    import numpy as np
    from sklearn.feature_extraction.text import HashingVectorizer

    dim = int(dimension)
    if dim <= 0:
        raise ValueError("dimension must be > 0")

    vectorizer = HashingVectorizer(
        n_features=dim,
        alternate_sign=False,
        norm=None,
        analyzer="word",
        ngram_range=(1, 2),
    )

    def embed_text(text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * dim
        X = vectorizer.transform([text])
        v = X.toarray()[0].astype("float32")
        n = float(np.linalg.norm(v))
        if n > 0:
            v = v / n
        return v.tolist()

    return EmbeddingBackend(model_name=f"hashing:{dim}", dimension=dim, embed_text=embed_text)

