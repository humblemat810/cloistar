from __future__ import annotations

"""Durable bridge store backed by the governance persistence service.

The bridge keeps the old store-facing method surface so endpoint code and
fixtures remain stable, but the source of truth now lives in durable Kogwistar
graph state rather than Python process memory.
"""

from dataclasses import dataclass
from typing import Any

from .domain.governance_models import ApprovalRequestedEvent, CanonicalGovernanceEvent, IntegrationReceipt


@dataclass
class PersistentGovernanceStore:
    """Bridge store facade that delegates persistence and queries to GovernanceService."""

    def _service(self):
        from .runtime import get_governance_runtime_host
        from .runtime.governance_service import GovernanceService

        host = get_governance_runtime_host()
        return GovernanceService.from_engine(
            host.conversation_engine,
            workflow_engine=host.workflow_engine,
        )

    def append_canonical_event(self, event: CanonicalGovernanceEvent) -> dict[str, Any]:
        row = event.model_dump(mode="json")
        self._service().persist_event_row(row)
        return row

    def record_receipt(self, receipt: IntegrationReceipt) -> dict[str, Any]:
        row = receipt.model_dump(mode="json")
        self._service().persist_receipt_row(row)
        return row

    def register_approval_request(
        self,
        event: ApprovalRequestedEvent,
        suspension_id: str,
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        observed = self._find_observed_event(snapshot, event.subject.governanceCallId)
        approval_id = event.data.approvalRequestId
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
        row = self._service().upsert_approval_row(approval_id, row)
        return self._attach_gateway_approval(row)

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
        row = {
            "gatewayApprovalId": gateway_approval_id,
            "kind": kind,
            "status": "pending",
            "request": dict(request_data),
            "createdAtMs": payload.get("createdAtMs"),
            "expiresAtMs": payload.get("expiresAtMs"),
        }
        row = self._service().upsert_gateway_approval_row(gateway_approval_id, row)
        self._attach_bridge_approval(row)
        self.update_approval_subscription_status(
            {
                "lastRequestedEventAt": payload.get("createdAtMs"),
                "lastStatusAt": payload.get("createdAtMs"),
            }
        )
        return dict(row)

    def resolve_gateway_approval(
        self,
        kind: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        gateway_approval_id = self._normalize_gateway_approval_id(payload.get("id"))
        if gateway_approval_id is None:
            return None
        existing = self._service().get_row("gateway_approval", gateway_approval_id) or {}
        request = payload.get("request")
        request_data = request if isinstance(request, dict) else {}
        row = {
            "gatewayApprovalId": gateway_approval_id,
            "kind": kind,
            "status": payload.get("decision") or "resolved",
            "request": dict(request_data) if request_data else existing.get("request") or {},
            "decision": payload.get("decision"),
            "resolvedBy": payload.get("resolvedBy"),
            "ts": payload.get("ts"),
            "bridgeApprovalId": existing.get("bridgeApprovalId"),
        }
        row = self._service().upsert_gateway_approval_row(gateway_approval_id, row)
        self._attach_bridge_approval(row)
        self.update_approval_subscription_status(
            {
                "lastResolvedEventAt": payload.get("ts"),
                "lastStatusAt": payload.get("ts"),
            }
        )
        return dict(row)

    def resolve_approval(
        self,
        approval_id: str,
        resolution: str,
        resolved_at: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_approval(approval_id)
        if current is None or current.get("status") != "pending":
            return None
        current["status"] = resolution
        current["resolvedAt"] = resolved_at or current.get("resolvedAt") or current["requestedAt"]
        return self._service().upsert_approval_row(approval_id, current)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        row = self._service().get_row("approval", approval_id)
        return dict(row) if isinstance(row, dict) else None

    def snapshot(self) -> dict[str, Any]:
        return self._service().materialize_debug_snapshot()

    def reset(self) -> None:
        service = self._service()
        service.reset_store()
        # Tests historically expected a clean runtime host between cases.
        from .runtime import reset_governance_runtime_host

        reset_governance_runtime_host()

    def upsert_workflow_run(self, governance_call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_workflow_run(governance_call_id) or {}
        current.update(payload)
        current["governanceCallId"] = governance_call_id
        return self._service().upsert_workflow_run_row(governance_call_id, current)

    def get_workflow_run(self, governance_call_id: str) -> dict[str, Any] | None:
        row = self._service().get_row("workflow_run", governance_call_id)
        return dict(row) if isinstance(row, dict) else None

    def upsert_governance_projection(self, governance_call_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._service().get_row("projection", governance_call_id) or {}
        current.update(payload)
        current["governanceCallId"] = governance_call_id
        persisted = self._service().upsert_projection_row(governance_call_id, current)
        workflow_run = self.get_workflow_run(governance_call_id)
        if workflow_run is not None:
            workflow_run["projection"] = dict(persisted)
            self._service().upsert_workflow_run_row(governance_call_id, workflow_run)
        return dict(persisted)

    def attach_runtime_to_approval(self, approval_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_approval(approval_id)
        if current is None:
            return None
        current.update(payload)
        return self._service().upsert_approval_row(approval_id, current)

    def update_approval_subscription_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self._service().get_row("approval_subscription", "latest") or {
            "enabled": False,
            "started": False,
            "connected": False,
            "lastError": None,
            "lastRequestedEventAt": None,
            "lastResolvedEventAt": None,
            "lastStatusAt": None,
        }
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
        return self._service().upsert_approval_subscription_row(current)

    def count_matching_approvals(self, tool_name: str) -> int:
        return self._service().count_matching_approvals(tool_name)

    @staticmethod
    def _normalize_gateway_approval_id(raw: Any) -> str | None:
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        return value or None

    @staticmethod
    def _find_observed_event(snapshot: dict[str, Any], governance_call_id: str) -> dict[str, Any]:
        for event in snapshot.get("events", []):
            if event.get("eventType") != "governance.tool_call_observed.v1":
                continue
            if event.get("subject", {}).get("governanceCallId") == governance_call_id:
                return event
        return {}

    def _attach_gateway_approval(self, approval_row: dict[str, Any]) -> dict[str, Any]:
        tool_call_id = approval_row.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return dict(approval_row)
        for gateway_row in self._service().list_rows("gateway_approval"):
            request = gateway_row.get("request")
            if not isinstance(request, dict) or request.get("toolCallId") != tool_call_id:
                continue
            approval_row["gatewayApprovalId"] = gateway_row["gatewayApprovalId"]
            self._service().upsert_approval_row(approval_row["approvalRequestId"], approval_row)
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            self._service().upsert_gateway_approval_row(gateway_row["gatewayApprovalId"], gateway_row)
            break
        return dict(approval_row)

    def _attach_bridge_approval(self, gateway_row: dict[str, Any]) -> None:
        request = gateway_row.get("request")
        if not isinstance(request, dict):
            return
        tool_call_id = request.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return
        for approval_row in self._service().list_rows("approval"):
            if approval_row.get("toolCallId") != tool_call_id:
                continue
            approval_row["gatewayApprovalId"] = gateway_row["gatewayApprovalId"]
            self._service().upsert_approval_row(approval_row["approvalRequestId"], approval_row)
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            self._service().upsert_gateway_approval_row(gateway_row["gatewayApprovalId"], gateway_row)
            return


store = PersistentGovernanceStore()
