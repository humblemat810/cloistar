from __future__ import annotations

from contextlib import contextmanager
from typing import Any, ClassVar


class _IdentityGeneric:
    def __class_getitem__(cls, item):
        return item


class DtoType(_IdentityGeneric):
    pass


class BackendType(_IdentityGeneric):
    pass


class _Marker:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class FrontendField(_Marker):
    pass


class BackendField(_Marker):
    pass


class LLMField(_Marker):
    pass


class ModeSlicingMixin:
    _mode_markers: ClassVar[dict[str, object]] = {}
    include_unmarked_for_modes: ClassVar[set[str]] = set()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._mode_markers = dict(getattr(cls, "_mode_markers", {}))
        cls.include_unmarked_for_modes = set(getattr(cls, "include_unmarked_for_modes", set()))

    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    @classmethod
    def register_mode(cls, name: str, marker: object) -> None:
        cls._mode_markers[name] = marker


@contextmanager
def use_mode(_mode: str):
    yield


from .mixin import DtoField, ExcludeMode

__all__ = [
    "BackendField",
    "BackendType",
    "DtoField",
    "DtoType",
    "ExcludeMode",
    "FrontendField",
    "LLMField",
    "ModeSlicingMixin",
    "use_mode",
]
