from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .domain.governance_models import ApprovalRequestedEvent, CanonicalGovernanceEvent, IntegrationReceipt


@dataclass
class InMemoryStore:
    events: list[dict[str, Any]] = field(default_factory=list)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def append_canonical_event(self, event: CanonicalGovernanceEvent) -> dict[str, Any]:
        row = event.model_dump(mode="json")
        with self._lock:
            self.events.append(row)
        return row

    def record_receipt(self, receipt: IntegrationReceipt) -> dict[str, Any]:
        row = receipt.model_dump(mode="json")
        with self._lock:
            self.receipts.append(row)
        return row

    def register_approval_request(
        self,
        event: ApprovalRequestedEvent,
        suspension_id: str,
    ) -> dict[str, Any]:
        approval_id = event.data.approvalRequestId
        with self._lock:
            row = {
                "approvalRequestId": approval_id,
                "governanceCallId": event.subject.governanceCallId,
                "decisionId": event.data.decisionId,
                "requestedEventId": event.eventId,
                "suspensionId": suspension_id,
                "status": event.data.status,
                "requestedAt": event.recordedAt.isoformat(),
                "projection": event.data.model_dump(mode="json"),
            }
            self.approvals[approval_id] = row
            return row

    def resolve_approval(
        self,
        approval_id: str,
        resolution: str,
        resolved_at: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            current = self.approvals.get(approval_id)
            if current is None:
                return None
            if current["status"] != "pending":
                return None
            current["status"] = resolution
            current["resolvedAt"] = resolved_at or current.get("resolvedAt") or current["requestedAt"]
            return dict(current)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            current = self.approvals.get(approval_id)
            if current is None:
                return None
            return dict(current)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": list(self.events),
                "approvals": dict(self.approvals),
                "receipts": list(self.receipts),
            }

    def reset(self) -> None:
        with self._lock:
            self.events.clear()
            self.approvals.clear()
            self.receipts.clear()


store = InMemoryStore()
