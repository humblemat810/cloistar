from __future__ import annotations


class ExcludeMode:
    def __init__(self, *modes: str) -> None:
        self.modes = modes


class DtoField:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
