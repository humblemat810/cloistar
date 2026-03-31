from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from threading import Lock
from typing import Any
import uuid


@dataclass
class InMemoryStore:
    events: list[dict[str, Any]] = field(default_factory=list)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "ts": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        with self._lock:
            self.events.append(row)
        return row

    def create_approval(self, payload: dict[str, Any]) -> str:
        approval_id = str(uuid.uuid4())
        with self._lock:
            self.approvals[approval_id] = {
                "approval_id": approval_id,
                "status": "pending",
                "payload": payload,
                "created_at": datetime.now(UTC).isoformat(),
            }
        return approval_id

    def resolve_approval(self, approval_id: str, resolution: str) -> dict[str, Any] | None:
        with self._lock:
            current = self.approvals.get(approval_id)
            if current is None:
                return None
            current["status"] = resolution
            current["resolved_at"] = datetime.now(UTC).isoformat()
            return current

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": list(self.events),
                "approvals": dict(self.approvals),
            }

    def reset(self) -> None:
        with self._lock:
            self.events.clear()
            self.approvals.clear()


store = InMemoryStore()
