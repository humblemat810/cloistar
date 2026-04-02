from __future__ import annotations

from typing import Any, Callable


class Memory:
    def __init__(self, location: str | None = None, *args, **kwargs) -> None:
        self.location = location
        self.args = args
        self.kwargs = kwargs

    def cache(self, fn: Callable[..., Any], *args, **kwargs) -> Callable[..., Any]:
        return fn
