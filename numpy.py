from __future__ import annotations

import math
from typing import Iterable


integer = int
floating = float


class ndarray(list):
    def __truediv__(self, other):
        return ndarray(float(value) / float(other) for value in self)

    def tolist(self):
        return list(self)


def asarray(values: Iterable[float], dtype=float):
    return ndarray(dtype(value) for value in values)


class _LinalgModule:
    @staticmethod
    def norm(values) -> float:
        return math.sqrt(sum(float(value) * float(value) for value in values))


linalg = _LinalgModule()
