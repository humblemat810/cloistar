from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _match_where(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        clauses = where.get("$and")
        if isinstance(clauses, list):
            return all(_match_where(metadata, clause) for clause in clauses if isinstance(clause, dict))
    for key, value in where.items():
        if key.startswith("$"):
            continue
        if metadata.get(key) != value:
            return False
    return True


@dataclass
class Collection:
    name: str
    embedding_function: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def add(self, *, ids, documents, metadatas, embeddings=None):
        for index, item_id in enumerate(ids):
            self._rows[str(item_id)] = {
                "id": str(item_id),
                "document": documents[index] if index < len(documents) else None,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "embedding": embeddings[index] if embeddings and index < len(embeddings) else None,
            }

    def upsert(self, *, ids, documents, metadatas, embeddings=None):
        for index, item_id in enumerate(ids):
            self._rows[str(item_id)] = {
                "id": str(item_id),
                "document": documents[index] if index < len(documents) else None,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "embedding": embeddings[index] if embeddings and index < len(embeddings) else None,
            }

    def update(self, *, ids, documents=None, metadatas=None, embeddings=None):
        for index, item_id in enumerate(ids):
            row = self._rows.setdefault(str(item_id), {"id": str(item_id), "document": None, "metadata": {}, "embedding": None})
            if documents is not None and index < len(documents):
                row["document"] = documents[index]
            if metadatas is not None and index < len(metadatas):
                patch = metadatas[index] or {}
                row["metadata"] = {**row.get("metadata", {}), **patch}
            if embeddings is not None and index < len(embeddings):
                row["embedding"] = embeddings[index]

    def get(self, *, ids=None, where=None, include=None, limit=None):
        rows = list(self._rows.values())
        if ids is not None:
            wanted = {str(item_id) for item_id in ids}
            rows = [row for row in rows if row["id"] in wanted]
        if where is not None:
            rows = [row for row in rows if _match_where(row.get("metadata", {}), where)]
        if limit is not None:
            rows = rows[:limit]
        include = include or ["documents", "metadatas"]
        output = {"ids": [row["id"] for row in rows]}
        if "documents" in include:
            output["documents"] = [row.get("document") for row in rows]
        if "metadatas" in include:
            output["metadatas"] = [row.get("metadata") for row in rows]
        if "embeddings" in include:
            output["embeddings"] = [row.get("embedding") for row in rows]
        return output

    def query(self, *, query_embeddings=None, n_results=10, where=None, include=None):
        rows = list(self._rows.values())
        if where is not None:
            rows = [row for row in rows if _match_where(row.get("metadata", {}), where)]
        rows = rows[:n_results]
        include = include or ["documents", "metadatas", "distances"]
        output = {"ids": [[row["id"] for row in rows]]}
        if "documents" in include:
            output["documents"] = [[row.get("document") for row in rows]]
        if "metadatas" in include:
            output["metadatas"] = [[row.get("metadata") for row in rows]]
        if "embeddings" in include:
            output["embeddings"] = [[row.get("embedding") for row in rows]]
        if "distances" in include:
            output["distances"] = [[0.0 for _ in rows]]
        return output

    def delete(self, *, ids=None, where=None):
        if ids is not None:
            for item_id in ids:
                self._rows.pop(str(item_id), None)
            return
        if where is not None:
            doomed = [row_id for row_id, row in self._rows.items() if _match_where(row.get("metadata", {}), where)]
            for row_id in doomed:
                self._rows.pop(row_id, None)
