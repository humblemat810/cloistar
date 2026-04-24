from __future__ import annotations

"""Durable bridge store backed by the governance persistence service.

The bridge keeps the old store-facing method surface so endpoint code and
fixtures remain stable, but the source of truth now lives in durable Kogwistar
graph state rather than Python process memory.
"""

from dataclasses import dataclass
from typing import Any, TypeVar, TypedDict

from .domain.governance_models import (
    ApprovalRuntimeAttachmentRow,
    ApprovalRequestedEvent,
    ApprovalRow,
    ApprovalSubscriptionStatusRow,
    CanonicalGovernanceEvent,
    DebugStateSnapshot,
    GatewayApprovalRequestedPayload,
    GatewayApprovalResolvedPayload,
    GatewayApprovalRequestRef,
    GatewayApprovalRow,
    GovernanceProjectionRow,
    IntegrationReceipt,
    WorkflowRunRow,
)


class PartialApprovalSubscriptionStatusRow(TypedDict, total=False):
    enabled: bool
    started: bool
    connected: bool
    lastError: str | None
    lastRequestedEventAt: int | None
    lastResolvedEventAt: int | None
    lastStatusAt: int | None


TGatewayApprovalRow = TypeVar("TGatewayApprovalRow", bound=GatewayApprovalRow)


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
        record = event.model_dump(mode="json")
        self._service().persist_event_record(record)
        return record

    def record_receipt(self, receipt: IntegrationReceipt) -> dict[str, Any]:
        record = receipt.model_dump(mode="json")
        self._service().persist_receipt_record(record)
        return record

    def register_approval_request(
        self,
        event: ApprovalRequestedEvent,
        suspension_id: str,
    ) -> ApprovalRow:
        snapshot = self.snapshot()
        observed = self._find_observed_event(snapshot, event.subject.governanceCallId)
        approval_id = event.data.approvalRequestId
        approval_record: ApprovalRow = {
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
        approval_record = self._service().upsert_approval_record(approval_id, approval_record)
        return self._attach_gateway_approval(approval_record)

    def register_gateway_approval(
        self,
        kind: str,
        payload: GatewayApprovalRequestedPayload,
    ) -> GatewayApprovalRow | None:
        gateway_approval_id = self._normalize_gateway_approval_id(payload.get("id"))
        if gateway_approval_id is None:
            return None
        request = payload.get("request")
        request_data: GatewayApprovalRequestRef = request if isinstance(request, dict) else {}
        gateway_record: GatewayApprovalRow = {
            "gatewayApprovalId": gateway_approval_id,
            "kind": kind,
            "status": "pending",
            "request": dict(request_data),
            "createdAtMs": payload.get("createdAtMs"),
            "expiresAtMs": payload.get("expiresAtMs"),
        }
        gateway_record = self._service().upsert_gateway_approval_record(gateway_approval_id, gateway_record)
        gateway_record = self._attach_bridge_approval(gateway_record)
        self.update_approval_subscription_status(
            {
                "lastRequestedEventAt": payload.get("createdAtMs"),
                "lastStatusAt": payload.get("createdAtMs"),
            }
        )
        return dict(gateway_record)

    def resolve_gateway_approval(
        self,
        kind: str,
        payload: GatewayApprovalResolvedPayload,
    ) -> GatewayApprovalRow | None:
        gateway_approval_id = self._normalize_gateway_approval_id(payload.get("id"))
        if gateway_approval_id is None:
            return None
        existing = self._service().get_record("gateway_approval", gateway_approval_id)
        request = payload.get("request")
        request_data: GatewayApprovalRequestRef = request if isinstance(request, dict) else {}
        gateway_record: GatewayApprovalRow = {
            "gatewayApprovalId": gateway_approval_id,
            "kind": kind,
            "status": payload.get("decision") or "resolved",
            "request": (
                dict(request_data)
                if request_data
                else dict(existing["request"])
                if existing is not None and "request" in existing
                else {}
            ),
            "decision": payload.get("decision"),
            "resolvedBy": payload.get("resolvedBy"),
            "ts": payload.get("ts"),
            "bridgeApprovalId": (
                existing["bridgeApprovalId"]
                if existing is not None and "bridgeApprovalId" in existing
                else None
            ),
        }
        gateway_record = self._service().upsert_gateway_approval_record(gateway_approval_id, gateway_record)
        gateway_record = self._attach_bridge_approval(gateway_record)
        self.update_approval_subscription_status(
            {
                "lastResolvedEventAt": payload.get("ts"),
                "lastStatusAt": payload.get("ts"),
            }
        )
        return dict(gateway_record)

    def resolve_approval(
        self,
        approval_id: str,
        resolution: str,
        resolved_at: str | None = None,
    ) -> ApprovalRow | None:
        current = self.get_approval(approval_id)
        if current is None or current.get("status") != "pending":
            return None
        current["status"] = resolution
        current["resolvedAt"] = resolved_at or current.get("resolvedAt") or current["requestedAt"]
        return self._service().upsert_approval_record(approval_id, current)

    def get_approval(self, approval_id: str) -> ApprovalRow | None:
        record = self._service().get_record("approval", approval_id)
        return dict(record) if isinstance(record, dict) else None

    def find_approval_for_gateway_request(self, request: GatewayApprovalRequestRef | dict[str, Any]) -> ApprovalRow | None:
        request_data = request if isinstance(request, dict) else {}
        tool_call_id = request_data.get("toolCallId")
        tool_name = request_data.get("toolName")
        session_key = request_data.get("sessionKey")

        exact_match: ApprovalRow | None = None
        fallback_match: ApprovalRow | None = None
        for approval_row in self._service().list_records("approval"):
            if approval_row.get("status") != "pending":
                continue
            if isinstance(tool_call_id, str) and tool_call_id and approval_row.get("toolCallId") == tool_call_id:
                exact_match = dict(approval_row)
                break
            if (
                exact_match is None
                and isinstance(tool_name, str)
                and tool_name
                and approval_row.get("toolName") == tool_name
                and isinstance(session_key, str)
                and session_key
                and approval_row.get("sessionId") == session_key
            ):
                fallback_match = dict(approval_row)
        return exact_match or fallback_match

    def find_approval_for_gateway_approval_id(self, gateway_approval_id: str) -> ApprovalRow | None:
        if not isinstance(gateway_approval_id, str) or not gateway_approval_id:
            return None
        approval_by_governance_call: dict[str, ApprovalRow] = {}
        for approval_row in self._service().list_records("approval"):
            if approval_row.get("status") != "pending":
                continue
            governance_call_id = approval_row.get("governanceCallId")
            if isinstance(governance_call_id, str) and governance_call_id:
                approval_by_governance_call[governance_call_id] = dict(approval_row)

        for receipt in self._service().list_records("receipt"):
            if receipt.get("sourceEventType") != "after_tool_call":
                continue
            payload = receipt.get("payload")
            if not isinstance(payload, dict):
                continue
            result = payload.get("result")
            if not isinstance(result, dict):
                continue
            details = result.get("details")
            if not isinstance(details, dict):
                continue
            if details.get("approvalId") != gateway_approval_id:
                continue
            governance_call_id = self._service()._receipt_governance_call_id(receipt)  # type: ignore[attr-defined]
            if isinstance(governance_call_id, str):
                approval_row = approval_by_governance_call.get(governance_call_id)
                if approval_row is not None:
                    return approval_row
                rebuilt = self._rebuild_pending_approval_from_events(governance_call_id)
                if rebuilt is not None:
                    return rebuilt
        return None

    def _rebuild_pending_approval_from_events(self, governance_call_id: str) -> ApprovalRow | None:
        """Recover one pending approval row from canonical events if projection rows are missing."""
        if not isinstance(governance_call_id, str) or not governance_call_id:
            return None

        snapshot = self.snapshot()
        events = snapshot.get("events", [])
        if not isinstance(events, list):
            return None

        observed_event: dict[str, Any] | None = None
        approval_events: list[dict[str, Any]] = []
        suspension_by_approval_id: dict[str, dict[str, Any]] = {}
        resolved_approval_ids: set[str] = set()

        for event in events:
            if not isinstance(event, dict):
                continue
            subject = event.get("subject")
            subject_data = subject if isinstance(subject, dict) else {}
            if subject_data.get("governanceCallId") != governance_call_id:
                continue

            event_type = event.get("eventType")
            if event_type == "governance.tool_call_observed.v1" and observed_event is None:
                observed_event = event
                continue
            if event_type == "governance.approval_requested.v1":
                approval_events.append(event)
                continue
            if event_type == "governance.execution_suspended.v1":
                approval_request_id = subject_data.get("approvalRequestId")
                if isinstance(approval_request_id, str) and approval_request_id:
                    suspension_by_approval_id[approval_request_id] = event
                continue
            if event_type == "governance.approval_resolved.v1":
                approval_request_id = subject_data.get("approvalRequestId")
                if isinstance(approval_request_id, str) and approval_request_id:
                    resolved_approval_ids.add(approval_request_id)

        workflow_run = self.get_workflow_run(governance_call_id) or {}
        projection = self._service().get_record("projection", governance_call_id) or workflow_run.get("projection")
        observed_data = observed_event.get("data", {}) if isinstance(observed_event, dict) else {}
        execution_context = observed_data.get("executionContext", {}) if isinstance(observed_data, dict) else {}
        tool_data = observed_data.get("tool", {}) if isinstance(observed_data, dict) else {}

        for approval_event in reversed(approval_events):
            if not isinstance(approval_event, dict):
                continue
            approval_data = approval_event.get("data")
            if not isinstance(approval_data, dict):
                continue
            approval_id = approval_data.get("approvalRequestId")
            if not isinstance(approval_id, str) or not approval_id:
                continue
            if approval_id in resolved_approval_ids:
                continue

            decision_id = approval_data.get("decisionId")
            requested_event_id = approval_event.get("eventId")
            suspension_event = suspension_by_approval_id.get(approval_id)
            suspension_data = suspension_event.get("data", {}) if isinstance(suspension_event, dict) else {}
            suspension_id = suspension_data.get("suspensionId")
            if not isinstance(decision_id, str) or not decision_id:
                continue
            if not isinstance(requested_event_id, str) or not requested_event_id:
                continue
            if not isinstance(suspension_id, str) or not suspension_id:
                continue

            requested_at = approval_event.get("recordedAt")
            status = approval_data.get("status")
            tool_call_id = execution_context.get("toolCallId")
            tool_name = tool_data.get("name")
            correlation_id = approval_event.get("correlationId")

            approval_record: ApprovalRow = {
                "approvalRequestId": approval_id,
                "governanceCallId": governance_call_id,
                "decisionId": decision_id,
                "requestedEventId": requested_event_id,
                "suspensionId": suspension_id,
                "status": status if isinstance(status, str) and status else "pending",
                "requestedAt": requested_at if isinstance(requested_at, str) and requested_at else "",
                "projection": dict(approval_data),
                "toolCallId": tool_call_id if isinstance(tool_call_id, str) and tool_call_id else None,
                "sessionId": correlation_id if isinstance(correlation_id, str) and correlation_id else None,
                "toolName": tool_name if isinstance(tool_name, str) and tool_name else None,
            }

            if isinstance(workflow_run.get("runId"), str):
                approval_record["workflowRunId"] = workflow_run["runId"]
            if isinstance(workflow_run.get("workflowId"), str):
                approval_record["workflowId"] = workflow_run["workflowId"]
            if isinstance(workflow_run.get("conversationId"), str):
                approval_record["runtimeConversationId"] = workflow_run["conversationId"]
            if isinstance(workflow_run.get("turnNodeId"), str):
                approval_record["runtimeTurnNodeId"] = workflow_run["turnNodeId"]
            if isinstance(workflow_run.get("suspendedNodeId"), str):
                approval_record["suspendedNodeId"] = workflow_run["suspendedNodeId"]
            if isinstance(workflow_run.get("suspendedTokenId"), str):
                approval_record["suspendedTokenId"] = workflow_run["suspendedTokenId"]
            if isinstance(projection, dict):
                approval_record["runtimeProjection"] = dict(projection)

            rebuilt = self._service().upsert_approval_record(approval_id, approval_record)
            return dict(rebuilt)

        return None

    def snapshot(self) -> DebugStateSnapshot:
        return self._service().materialize_debug_snapshot()

    def reset(self) -> None:
        service = self._service()
        service.reset_store()
        # Tests historically expected a clean runtime host between cases.
        from .runtime import reset_governance_runtime_host

        reset_governance_runtime_host()

    def upsert_workflow_run(self, governance_call_id: str, payload: WorkflowRunRow) -> WorkflowRunRow:
        current = self.get_workflow_run(governance_call_id) or {}
        current.update(payload)
        current["governanceCallId"] = governance_call_id
        return self._service().upsert_workflow_run_record(governance_call_id, current)

    def get_workflow_run(self, governance_call_id: str) -> WorkflowRunRow | None:
        record = self._service().get_record("workflow_run", governance_call_id)
        return dict(record) if isinstance(record, dict) else None

    def upsert_governance_projection(
        self,
        governance_call_id: str,
        payload: GovernanceProjectionRow,
    ) -> GovernanceProjectionRow:
        current = self._service().get_record("projection", governance_call_id) or {}
        current.update(payload)
        current["governanceCallId"] = governance_call_id
        persisted = self._service().upsert_projection_record(governance_call_id, current)
        workflow_run = self.get_workflow_run(governance_call_id)
        if workflow_run is not None:
            workflow_run["projection"] = dict(persisted)
            self._service().upsert_workflow_run_record(governance_call_id, workflow_run)
        return dict(persisted)

    def attach_runtime_to_approval(
        self,
        approval_id: str,
        payload: ApprovalRuntimeAttachmentRow,
    ) -> ApprovalRow | None:
        current = self.get_approval(approval_id)
        if current is None:
            return None
        current.update(payload)
        return self._service().upsert_approval_record(approval_id, current)

    def update_approval_subscription_status(
        self,
        payload: PartialApprovalSubscriptionStatusRow,
    ) -> ApprovalSubscriptionStatusRow:
        current: ApprovalSubscriptionStatusRow = self._service().get_record("approval_subscription", "latest") or {
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
        return self._service().upsert_approval_subscription_record(current)

    def count_matching_approvals(self, tool_name: str) -> int:
        return self._service().count_matching_approvals(tool_name)

    @staticmethod
    def _normalize_gateway_approval_id(raw: Any) -> str | None:
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        return value or None

    @staticmethod
    def _find_observed_event(snapshot: DebugStateSnapshot, governance_call_id: str) -> dict[str, Any]:
        for event in snapshot.get("events", []):
            if event.get("eventType") != "governance.tool_call_observed.v1":
                continue
            if event.get("subject", {}).get("governanceCallId") == governance_call_id:
                return event
        return {}

    def _attach_gateway_approval(self, approval_row: ApprovalRow) -> ApprovalRow:
        tool_call_id = approval_row.get("toolCallId")
        for gateway_row in self._service().list_records("gateway_approval"):
            gateway_approval_id = gateway_row.get("gatewayApprovalId")
            if not isinstance(gateway_approval_id, str) or not gateway_approval_id:
                continue
            matched = False
            request = gateway_row.get("request")
            if isinstance(tool_call_id, str) and tool_call_id and isinstance(request, dict):
                matched = request.get("toolCallId") == tool_call_id
            if not matched:
                receipt_match = self.find_approval_for_gateway_approval_id(gateway_approval_id)
                matched = (
                    receipt_match is not None
                    and receipt_match.get("approvalRequestId") == approval_row.get("approvalRequestId")
                )
            if not matched:
                continue
            approval_row["gatewayApprovalId"] = gateway_approval_id
            self._service().upsert_approval_record(approval_row["approvalRequestId"], approval_row)
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            self._service().upsert_gateway_approval_record(gateway_approval_id, gateway_row)
            break
        return dict(approval_row)

    def _attach_bridge_approval(self, gateway_row: TGatewayApprovalRow) -> TGatewayApprovalRow:
        request = gateway_row.get("request")
        request_match = self.find_approval_for_gateway_request(request) if isinstance(request, dict) else None
        receipt_match = self.find_approval_for_gateway_approval_id(gateway_row["gatewayApprovalId"])
        approval_row = request_match or receipt_match
        if approval_row is not None:
            approval_row["gatewayApprovalId"] = gateway_row["gatewayApprovalId"]
            self._service().upsert_approval_record(approval_row["approvalRequestId"], approval_row)
            gateway_row["bridgeApprovalId"] = approval_row["approvalRequestId"]
            self._service().upsert_gateway_approval_record(gateway_row["gatewayApprovalId"], gateway_row)
            return gateway_row
        return gateway_row


store = PersistentGovernanceStore()
