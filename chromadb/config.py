from __future__ import annotations


class Settings:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)
