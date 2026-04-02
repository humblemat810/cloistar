from __future__ import annotations

from dataclasses import dataclass

from .collection import Collection


@dataclass
class Client:
    settings: object | None = None

    def __post_init__(self) -> None:
        self._collections: dict[str, Collection] = {}

    def get_or_create_collection(self, name: str, embedding_function=None, metadata=None):
        collection = self._collections.get(name)
        if collection is None:
            collection = Collection(
                name=name,
                embedding_function=embedding_function,
                metadata=metadata or {},
            )
            self._collections[name] = collection
        return collection
