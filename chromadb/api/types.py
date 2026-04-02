from __future__ import annotations

Embeddings = list[list[float]]


class EmbeddingFunction:
    @staticmethod
    def name() -> str:
        return "shim"
