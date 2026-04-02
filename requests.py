from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RequestException(Exception):
    pass


@dataclass
class Response:
    status_code: int = 200
    text: str = ""

    def json(self) -> dict[str, Any]:
        return {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RequestException(f"HTTP {self.status_code}")


def post(*args, **kwargs) -> Response:
    return Response()
