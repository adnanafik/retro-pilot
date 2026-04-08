"""Sentence-transformers embedder wrapper for retro-pilot.

Uses all-MiniLM-L6-v2 (80MB, CPU-compatible) to produce 384-dim vectors.
Model is loaded once at construction and reused across all calls.
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps SentenceTransformer for post-mortem embedding.

    Args:
        model_name: HuggingFace model ID. Default: all-MiniLM-L6-v2.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a list of floats."""
        vector = self._model.encode(text)
        return vector.tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple strings in one batch pass."""
        vectors = self._model.encode(texts)
        return [v.tolist() for v in vectors]
