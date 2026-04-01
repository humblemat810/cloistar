from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .domain.governance_models import ApprovalRequestedEvent, CanonicalGovernanceEvent, IntegrationReceipt


@dataclass
class InMemoryStore:
    events: list[dict[str, Any]] = field(default_factory=list)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    gateway_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_subscription: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": False,
            "started": False,
            "connected": False,
            "lastError": None,
            "lastRequestedEventAt": None,
            "lastResolvedEventAt": None,
            "lastStatusAt": None,
        }
    )
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
            observed = self._find_observed_event_locked(event.subject.governanceCallId)
            row = {
                "approvalRequestId": approval_id,
                "governanceCallId": event.subject.governanceCallId,
                "decisionId": event.data.decisionId,
                "requestedEventId": event.eventId,
                "suspensionId": suspension_id,
                "status": event.data.status,
                "requestedAt": event.recordedAt.isoformat(),
                "projection": event.data.model_dump(mode="json"),
                "toolCallId": observed.get("data", {}).get("executionContext", {}).get("toolCallId"),
                "sessionId": event.correlationId,
                "toolName": observed.get("data", {}).get("tool", {}).get("name"),
            }
            self.approvals[approval_id] = row
            self._attach_gateway_approval_locked(row)
            return row

    def register_gateway_approval(
        self,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        gateway_approval_id = self._normalize_gateway_approval_id(payload.get("id"))
        if gateway_approval_id is None:
            return None
        request = payload.get("request")
        request_data = request if isinstance(request, dict) else {}
        with self._lock:
            row = {
                "gatewayApprovalId": gateway_approval_id,
                "kind": kind,
                "status": "pending",
                "request": dict(request_data),
                "createdAtMs": payload.get("createdAtMs"),
                "expiresAtMs": payload.get("expiresAtMs"),
            }
            self.gateway_approvals[gateway_approval_id] = row
            self._attach_bridge_approval_locked(row)
            self.approval_subscription["lastRequestedEventAt"] = payload.get("createdAtMs")
            self.approval_subscription["lastStatusAt"] = payload.get("createdAtMs")
            return dict(row)

    def resolve_gateway_approval(
        self,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        gateway_approval_id = self._normalize_gateway_approval_id(payload.get("id"))
        if gateway_approval_id is None:
            return None
        request = payload.get("request")
        request_data = request if isinstance(request, dict) else {}
        with self._lock:
            current = self.gateway_approvals.get(gateway_approval_id)
            if current is None:
                current = {
                    "gatewayApprovalId": gateway_approval_id,
                    "kind": kind,
                    "status": "resolved",
                    "request": dict(request_data),
                }
                self.gateway_approvals[gateway_approval_id] = current
            current["status"] = payload.get("decision") or "resolved"
            current["decision"] = payload.get("decision")
            current["resolvedBy"] = payload.get("resolvedBy")
            current["ts"] = payload.get("ts")
            if request_data and not current.get("request"):
                current["request"] = dict(request_data)
            self._attach_bridge_approval_locked(current)
            self.approval_subscription["lastResolvedEventAt"] = payload.get("ts")
            self.approval_subscription["lastStatusAt"] = payload.get("ts")
            return dict(current)

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
                "gatewayApprovals": dict(self.gateway_approvals),
                "approvalSubscription": dict(self.approval_subscription),
                "receipts": list(self.receipts),
            }

    def reset(self) -> None:
        with self._lock:
            self.events.clear()
            self.approvals.clear()
            self.gateway_approvals.clear()
            self.approval_subscription = {
                "enabled": False,
                "started": False,
                "connected": False,
                "lastError": None,
                "lastRequestedEventAt": None,
                "lastResolvedEventAt": None,
                "lastStatusAt": None,
            }
            self.receipts.clear()

    def update_approval_subscription_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = dict(self.approval_subscription)
            for key in (
                "enabled",
                "started",
                "connected",
                "lastError",
                "lastRequestedEventAt",
                "lastResolvedEventAt",
                "lastStatusAt",
            ):
                if key in payload:
                    current[key] = payload[key]
            self.approval_subscription = current
            return dict(current)

    @staticmethod
    def _normalize_gateway_approval_id(raw: Any) -> str | None:
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        return value or None

    def _attach_gateway_approval_locked(self, approval_row: dict[str, Any]) -> None:
        tool_call_id = approval_row.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return
        for gateway_row in self.gateway_approvals.values():
            request = gateway_row.get("request")
            if not isinstance(request, dict):
                continue
            if request.get("toolCallId") != tool_call_id:
                continue
            approval_row["gatewayApprovalId"] = gateway_row["gatewayApprovalId"]
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            return

    def _attach_bridge_approval_locked(self, gateway_row: dict[str, Any]) -> None:
        request = gateway_row.get("request")
        if not isinstance(request, dict):
            return
        tool_call_id = request.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return
        for approval_row in self.approvals.values():
            if approval_row.get("toolCallId") != tool_call_id:
                continue
            approval_row["gatewayApprovalId"] = gateway_row["gatewayApprovalId"]
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            return

    def _find_observed_event_locked(self, governance_call_id: str) -> dict[str, Any]:
        for event in reversed(self.events):
            if event.get("eventType") != "governance.tool_call_observed.v1":
                continue
            subject = event.get("subject")
            if not isinstance(subject, dict):
                continue
            if subject.get("governanceCallId") == governance_call_id:
                return event
        return {}


store = InMemoryStore()
