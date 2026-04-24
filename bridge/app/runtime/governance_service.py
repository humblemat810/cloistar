from __future__ import annotations

"""Durable governance persistence facade.

This module mirrors the role that ``ConversationService`` plays for the chat
domain: one service-level boundary over append-only graph writes and a
rebuildable latest-state projection for operator/debug queries.

The service intentionally reuses core Kogwistar substrate models instead of
introducing a separate governance-only storage primitive. Governance semantics
come from metadata, deterministic ids, and backbone/link relations.
"""

from dataclasses import dataclass
import hashlib
import json
import os
import sys
import time
from typing import Any, Literal, Protocol, Sequence, TypeAlias, overload

from kogwistar.engine_core.models import Node

from ..domain.governance_models import (
    ApprovalRow,
    ApprovalSubscriptionStatusRow,
    GatewayApprovalRow,
    GovernanceProjectionRow,
    IntegrationReceipt,
    WorkflowRunRow,
    stable_governance_call_id,
)
from .governance_graph import governance_edge, governance_grounding, governance_node


STORE_RECORD_ENTITY = "governance_store_record"
BACKBONE_ENTITY = "governance_backbone_step"
STORE_DOC_IDS = {
    "events": "gov-store:events",
    "receipts": "gov-store:receipts",
    "approvals": "gov-store:approvals",
    "gateway_approvals": "gov-store:gateway-approvals",
    "workflow_runs": "gov-store:workflow-runs",
    "governance_projection": "gov-store:governance-projection",
    "approval_subscription": "gov-store:approval-subscription",
}
BACKBONE_DOC_ID = "gov-store:backbone"
STORE_RESET_DOC_IDS = list(STORE_DOC_IDS.values()) + [BACKBONE_DOC_ID]
BRIDGE_GOVERNANCE_PROJECTION_NAMESPACE = "bridge_governance"
_SERVICE_CACHE: dict[tuple[int, int | None], "GovernanceService"] = {}
RecordKind: TypeAlias = Literal[
    "event",
    "receipt",
    "approval",
    "gateway_approval",
    "workflow_run",
    "projection",
    "approval_subscription",
]
CanonicalGovernanceEventRow: TypeAlias = dict[str, Any]
IntegrationReceiptRow: TypeAlias = dict[str, Any]
GovernanceRecord: TypeAlias = (
    CanonicalGovernanceEventRow
    | IntegrationReceiptRow
    | ApprovalRow
    | GatewayApprovalRow
    | WorkflowRunRow
    | GovernanceProjectionRow
    | ApprovalSubscriptionStatusRow
)
StructuredRecordKind: TypeAlias = Literal[
    "approval",
    "gateway_approval",
    "workflow_run",
    "projection",
    "approval_subscription",
]
STRUCTURED_RECORD_KINDS: tuple[StructuredRecordKind, ...] = (
    "approval",
    "gateway_approval",
    "workflow_run",
    "projection",
    "approval_subscription",
)
SEMANTIC_EVENT_ENTITY_TYPES: dict[str, str] = {
    "governance.tool_call_observed.v1": "governance_proposal",
    "governance.decision_recorded.v1": "governance_decision",
    "governance.approval_requested.v1": "governance_approval_request",
    "governance.approval_resolved.v1": "governance_approval_resolution",
    "governance.result_recorded.v1": "governance_result",
    "governance.completed.v1": "governance_completed",
    "governance.tool_call_completed.v1": "governance_completion",
}
GENERIC_EVENT_ENTITY_TYPE = "governance_event"


def _approval_debug_enabled() -> bool:
    value = os.getenv("BRIDGE_APPROVAL_DEBUG", "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _approval_debug(message: str, **fields: object) -> None:
    if not _approval_debug_enabled():
        return
    detail = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields))
    print(f"[governance-service-debug] {message}" + (f" {detail}" if detail else ""), file=sys.stderr, flush=True)


class GraphWritePort(Protocol):
    def add_node(self, node: Any) -> Any: ...

    def add_edge(self, edge: Any) -> Any: ...


class GraphRollbackPort(Protocol):
    def rollback_document(self, doc_id: str) -> Any: ...


class GraphEnginePort(Protocol):
    persist_directory: str | None
    write: GraphWritePort
    rollback: GraphRollbackPort
    meta_sqlite: Any


@dataclass
class GovernanceService:
    """Service facade for durable governance state and debug projections."""

    conversation_engine: GraphEnginePort
    workflow_engine: GraphEnginePort | None = None

    @classmethod
    def from_engine(
        cls,
        conversation_engine: GraphEnginePort,
        *,
        workflow_engine: GraphEnginePort | None = None,
    ) -> "GovernanceService":
        """Return a cached service instance for one engine pair."""
        cache_key = (id(conversation_engine), id(workflow_engine) if workflow_engine is not None else None)
        service = _SERVICE_CACHE.get(cache_key)
        if service is not None:
            return service
        service = cls(
            conversation_engine=conversation_engine,
            workflow_engine=workflow_engine,
        )
        _SERVICE_CACHE[cache_key] = service
        return service

    def reset_store(self) -> None:
        """Delete durable governance store documents used by tests and local runs."""
        for doc_id in STORE_RESET_DOC_IDS:
            try:
                self.conversation_engine.rollback.rollback_document(doc_id)
            except Exception:
                # Durable reset is best-effort; a missing doc is not an error.
                continue
        self._clear_projection_namespace()

    def persist_event_record(self, event_record: CanonicalGovernanceEventRow) -> CanonicalGovernanceEventRow:
        """Persist one canonical governance event record and attach it to the backbone."""
        event_id = str(event_record["eventId"])
        event_type = str(event_record["eventType"])
        governance_call_id = str(event_record["subject"]["governanceCallId"])
        backbone_step, backbone_relation = self._persist_backbone_for_event(governance_call_id, event_record)
        node_id = self._persist_record(
            record_kind="event",
            record_id=event_id,
            payload=event_record,
            doc_id=STORE_DOC_IDS["events"],
            metadata={
                "entity_type": self._event_entity_type(event_type),
                "event_type": event_type,
                "governance_call_id": governance_call_id,
                "approval_request_id": event_record.get("subject", {}).get("approvalRequestId"),
            },
            label=event_type,
            summary=f"Canonical governance event {event_type}",
        )
        if backbone_step is not None and backbone_relation is not None:
            self._link_event_to_backbone(
                governance_call_id,
                node_id,
                backbone_step,
                backbone_relation,
            )
        self._persist_semantic_event_relations(governance_call_id, event_record, event_node_id=node_id)
        self._link_matching_receipts(governance_call_id, event_record, event_node_id=node_id)
        self._reconcile_semantic_event_relations(governance_call_id)
        return dict(event_record)

    def persist_receipt_record(
        self,
        receipt_record: IntegrationReceiptRow | IntegrationReceipt,
    ) -> IntegrationReceiptRow:
        """Persist one integration receipt record."""
        receipt_data = dict(receipt_record)
        self._persist_record(
            record_kind="receipt",
            record_id=str(receipt_data["receiptId"]),
            payload=receipt_data,
            doc_id=STORE_DOC_IDS["receipts"],
            metadata={
                "receipt_id": str(receipt_data["receiptId"]),
                "source_event_type": str(receipt_data["sourceEventType"]),
                "session_id": receipt_data.get("payload", {}).get("sessionId"),
                "tool_call_id": receipt_data.get("payload", {}).get("rawEvent", {}).get("toolCallId"),
            },
            label=f"Receipt {receipt_data['sourceEventType']}",
            summary=f"Receipt for {receipt_data['sourceEventType']}",
        )
        return receipt_data

    def upsert_approval_record(self, approval_id: str, payload: ApprovalRow) -> ApprovalRow:
        """Persist one approval summary record with stable identity."""
        record: ApprovalRow = payload
        record["approvalRequestId"] = approval_id
        _approval_debug(
            "upsert_approval_record:start",
            approvalId=approval_id,
            governanceCallId=record.get("governanceCallId"),
            status=record.get("status"),
            sessionId=record.get("sessionId"),
            toolName=record.get("toolName"),
            gatewayApprovalId=record.get("gatewayApprovalId"),
        )
        self._persist_record(
            record_kind="approval",
            record_id=approval_id,
            payload=record,
            doc_id=STORE_DOC_IDS["approvals"],
            metadata={
                "approval_request_id": approval_id,
                "governance_call_id": record.get("governanceCallId"),
                "tool_call_id": record.get("toolCallId"),
                "tool_name": record.get("toolName"),
                "status": record.get("status"),
                "gateway_approval_id": record.get("gatewayApprovalId"),
            },
            label=f"Approval {approval_id}",
            summary=f"Approval record for {record.get('toolName') or 'tool'}",
        )
        self._project_latest_record("approval", approval_id, record)
        _approval_debug(
            "upsert_approval_record:done",
            approvalId=approval_id,
            projectedNamespace=BRIDGE_GOVERNANCE_PROJECTION_NAMESPACE,
            projectionKey=self._projection_key("approval", approval_id),
        )
        return record

    def upsert_gateway_approval_record(
        self,
        gateway_approval_id: str,
        payload: GatewayApprovalRow,
    ) -> GatewayApprovalRow:
        """Persist one gateway approval record with stable identity."""
        record: GatewayApprovalRow = payload
        record["gatewayApprovalId"] = gateway_approval_id
        request = record.get("request")
        request_data = request if isinstance(request, dict) else {}
        self._persist_record(
            record_kind="gateway_approval",
            record_id=gateway_approval_id,
            payload=record,
            doc_id=STORE_DOC_IDS["gateway_approvals"],
            metadata={
                "gateway_approval_id": gateway_approval_id,
                "tool_call_id": request_data.get("toolCallId"),
                "kind": record.get("kind"),
                "status": record.get("status"),
                "bridge_approval_id": record.get("bridgeApprovalId"),
            },
            label=f"Gateway approval {gateway_approval_id}",
            summary="OpenClaw gateway approval record",
        )
        self._project_latest_record("gateway_approval", gateway_approval_id, record)
        _approval_debug(
            "upsert_gateway_approval_record",
            gatewayApprovalId=gateway_approval_id,
            kind=record.get("kind"),
            status=record.get("status"),
            decision=record.get("decision"),
            bridgeApprovalId=record.get("bridgeApprovalId"),
        )
        return record

    def upsert_workflow_run_record(
        self,
        governance_call_id: str,
        payload: WorkflowRunRow,
    ) -> WorkflowRunRow:
        """Persist a workflow-run summary record keyed by governance call id."""
        record: WorkflowRunRow = payload
        record["governanceCallId"] = governance_call_id
        self._persist_record(
            record_kind="workflow_run",
            record_id=governance_call_id,
            payload=record,
            doc_id=STORE_DOC_IDS["workflow_runs"],
            metadata={
                "governance_call_id": governance_call_id,
                "workflow_id": record.get("workflowId"),
                "run_id": record.get("runId"),
                "status": record.get("status"),
                "decision": record.get("decision"),
                "final_disposition": record.get("finalDisposition"),
            },
            label=f"Workflow run {governance_call_id}",
            summary=f"Workflow summary for governance call {governance_call_id}",
        )
        self._project_latest_record("workflow_run", governance_call_id, record)
        return record

    def upsert_projection_record(
        self,
        governance_call_id: str,
        payload: GovernanceProjectionRow,
    ) -> GovernanceProjectionRow:
        """Persist a governance projection record keyed by governance call id."""
        record: GovernanceProjectionRow = payload
        record["governanceCallId"] = governance_call_id
        self._persist_record(
            record_kind="projection",
            record_id=governance_call_id,
            payload=record,
            doc_id=STORE_DOC_IDS["governance_projection"],
            metadata={
                "governance_call_id": governance_call_id,
                "proposal_node_id": record.get("proposalNodeId"),
                "decision_node_id": record.get("decisionNodeId"),
                "approval_node_id": record.get("approvalNodeId"),
                "resolution_node_id": record.get("resolutionNodeId"),
                "completion_node_id": record.get("completionNodeId"),
            },
            label=f"Projection {governance_call_id}",
            summary=f"Projection for governance call {governance_call_id}",
        )
        self._project_latest_record("projection", governance_call_id, record)
        return record

    def upsert_approval_subscription_record(
        self,
        payload: ApprovalSubscriptionStatusRow,
    ) -> ApprovalSubscriptionStatusRow:
        """Persist the latest approval-listener subscription record."""
        record: ApprovalSubscriptionStatusRow = payload
        self._persist_record(
            record_kind="approval_subscription",
            record_id="latest",
            payload=record,
            doc_id=STORE_DOC_IDS["approval_subscription"],
            metadata={
                "enabled": record.get("enabled"),
                "started": record.get("started"),
                "connected": record.get("connected"),
                "last_error": record.get("lastError"),
            },
            label="Approval subscription status",
            summary="Latest gateway approval listener status",
        )
        self._project_latest_record("approval_subscription", "latest", record)
        return record

    @overload
    def get_record(self, record_kind: Literal["event"], record_id: str) -> CanonicalGovernanceEventRow | None: ...

    @overload
    def get_record(self, record_kind: Literal["receipt"], record_id: str) -> IntegrationReceiptRow | None: ...

    @overload
    def get_record(self, record_kind: Literal["approval"], record_id: str) -> ApprovalRow | None: ...

    @overload
    def get_record(self, record_kind: Literal["gateway_approval"], record_id: str) -> GatewayApprovalRow | None: ...

    @overload
    def get_record(self, record_kind: Literal["workflow_run"], record_id: str) -> WorkflowRunRow | None: ...

    @overload
    def get_record(self, record_kind: Literal["projection"], record_id: str) -> GovernanceProjectionRow | None: ...

    @overload
    def get_record(
        self,
        record_kind: Literal["approval_subscription"],
        record_id: str,
    ) -> ApprovalSubscriptionStatusRow | None: ...

    def get_record(self, record_kind: RecordKind, record_id: str) -> GovernanceRecord | None:
        """Return one persisted record payload by kind and stable record id."""
        records = self._load_records(record_kind)
        if isinstance(records, dict):
            record = records.get(record_id)
            return dict(record) if isinstance(record, dict) else None
        for record in records:
            if isinstance(record, dict) and str(record.get(self._record_id_key(record_kind), "")) == record_id:
                return dict(record)
        return None

    @overload
    def list_records(self, record_kind: Literal["event"]) -> list[CanonicalGovernanceEventRow]: ...

    @overload
    def list_records(self, record_kind: Literal["receipt"]) -> list[IntegrationReceiptRow]: ...

    @overload
    def list_records(self, record_kind: Literal["approval"]) -> list[ApprovalRow]: ...

    @overload
    def list_records(self, record_kind: Literal["gateway_approval"]) -> list[GatewayApprovalRow]: ...

    @overload
    def list_records(self, record_kind: Literal["workflow_run"]) -> list[WorkflowRunRow]: ...

    @overload
    def list_records(self, record_kind: Literal["projection"]) -> list[GovernanceProjectionRow]: ...

    @overload
    def list_records(self, record_kind: Literal["approval_subscription"]) -> list[ApprovalSubscriptionStatusRow]: ...

    def list_records(self, record_kind: RecordKind) -> Sequence[GovernanceRecord]:
        """Return all persisted records for one logical record kind."""
        records = self._load_records(record_kind)
        if isinstance(records, dict):
            return [dict(record) for record in records.values() if isinstance(record, dict)]
        return [dict(record) for record in records if isinstance(record, dict)]

    def count_matching_approvals(self, tool_name: str) -> int:
        """Count approvals for one tool from durable persisted records."""
        return sum(1 for record in self.list_records("approval") if record.get("toolName") == tool_name)

    def materialize_debug_snapshot(self) -> dict[str, Any]:
        """Build the bridge debug-state shape from durable record nodes."""
        events = self._sorted_records(self.list_records("event"), keys=("recordedAt", "occurredAt", "eventId"))
        receipts = self._sorted_records(self.list_records("receipt"), keys=("receivedAt", "receiptId"))
        workflow_runs: dict[str, WorkflowRunRow] = {}
        for record in self.list_records("workflow_run"):
            governance_call_id = record.get("governanceCallId")
            if isinstance(governance_call_id, str):
                workflow_runs[governance_call_id] = record

        governance_projection: dict[str, GovernanceProjectionRow] = {}
        for record in self.list_records("projection"):
            governance_call_id = record.get("governanceCallId")
            if isinstance(governance_call_id, str):
                governance_projection[governance_call_id] = record

        approvals: dict[str, ApprovalRow] = {}
        for record in self.list_records("approval"):
            approval_request_id = record.get("approvalRequestId")
            if not isinstance(approval_request_id, str):
                continue
            approval_record = dict(record)
            governance_call_id = approval_record.get("governanceCallId")
            workflow_run = workflow_runs.get(governance_call_id) if isinstance(governance_call_id, str) else None
            projection = governance_projection.get(governance_call_id) if isinstance(governance_call_id, str) else None
            if workflow_run is not None:
                approval_record.setdefault("workflowRunId", workflow_run.get("runId"))
                approval_record.setdefault("workflowId", workflow_run.get("workflowId"))
                approval_record.setdefault("runtimeConversationId", workflow_run.get("conversationId"))
                approval_record.setdefault("runtimeTurnNodeId", workflow_run.get("turnNodeId"))
                approval_record.setdefault("suspendedNodeId", workflow_run.get("suspendedNodeId"))
                approval_record.setdefault("suspendedTokenId", workflow_run.get("suspendedTokenId"))
            if projection is not None:
                approval_record.setdefault("runtimeProjection", projection)
            approvals[approval_request_id] = approval_record

        gateway_approvals: dict[str, GatewayApprovalRow] = {}
        for record in self.list_records("gateway_approval"):
            gateway_approval_id = record.get("gatewayApprovalId")
            if isinstance(gateway_approval_id, str):
                gateway_record = dict(record)
                status = gateway_record.get("status")
                if "decision" not in gateway_record and isinstance(status, str) and status not in {"pending", "resolved"}:
                    gateway_record["decision"] = status
                gateway_approvals[gateway_approval_id] = gateway_record

        # Bridge approval records and gateway approval records are persisted as
        # separate stable-id records. Reattach their cross-link here so the
        # debug snapshot stays consistent even if one side was written first.
        for gateway_approval_id, gateway_record in gateway_approvals.items():
            bridge_approval_id = gateway_record.get("bridgeApprovalId")
            if isinstance(bridge_approval_id, str):
                approval_record = approvals.get(bridge_approval_id)
                if approval_record is not None:
                    approval_record.setdefault("gatewayApprovalId", gateway_approval_id)
                    continue
            request = gateway_record.get("request")
            tool_call_id = request.get("toolCallId") if isinstance(request, dict) else None
            if not isinstance(tool_call_id, str):
                continue
            for approval_record in approvals.values():
                if approval_record.get("toolCallId") == tool_call_id:
                    approval_record.setdefault("gatewayApprovalId", gateway_approval_id)
                    gateway_record.setdefault("bridgeApprovalId", approval_record.get("approvalRequestId"))
                    break

        for approval_request_id, approval_record in approvals.items():
            gateway_approval_id = approval_record.get("gatewayApprovalId")
            if not isinstance(gateway_approval_id, str):
                continue
            gateway_record = gateway_approvals.get(gateway_approval_id)
            if gateway_record is not None:
                gateway_record.setdefault("bridgeApprovalId", approval_request_id)

        subscription_records = self.list_records("approval_subscription")
        approval_subscription = subscription_records[-1] if subscription_records else {
            "enabled": False,
            "started": False,
            "connected": False,
            "lastError": None,
            "lastRequestedEventAt": None,
            "lastResolvedEventAt": None,
            "lastStatusAt": None,
        }
        if not isinstance(approval_subscription, dict):
            approval_subscription = {
                "enabled": False,
                "started": False,
                "connected": False,
                "lastError": None,
                "lastRequestedEventAt": None,
                "lastResolvedEventAt": None,
                "lastStatusAt": None,
            }
        for key, default in (
            ("enabled", False),
            ("started", False),
            ("connected", False),
            ("lastError", None),
            ("lastRequestedEventAt", None),
            ("lastResolvedEventAt", None),
            ("lastStatusAt", None),
        ):
            approval_subscription.setdefault(key, default)
        if approval_subscription.get("lastRequestedEventAt") is None:
            requested_values = [
                gateway_record.get("createdAtMs")
                for gateway_record in gateway_approvals.values()
                if isinstance(gateway_record.get("createdAtMs"), int)
            ]
            if requested_values:
                approval_subscription["lastRequestedEventAt"] = max(requested_values)
        if approval_subscription.get("lastResolvedEventAt") is None:
            resolved_values = [
                gateway_record.get("ts")
                for gateway_record in gateway_approvals.values()
                if isinstance(gateway_record.get("ts"), int)
            ]
            if resolved_values:
                approval_subscription["lastResolvedEventAt"] = max(resolved_values)
        if approval_subscription.get("lastStatusAt") is None:
            status_values = [
                value
                for value in (
                    approval_subscription.get("lastResolvedEventAt"),
                    approval_subscription.get("lastRequestedEventAt"),
                )
                if isinstance(value, int)
            ]
            if status_values:
                approval_subscription["lastStatusAt"] = max(status_values)
        return {
            "events": events,
            "approvals": approvals,
            "gatewayApprovals": gateway_approvals,
            "workflowRuns": workflow_runs,
            "governanceProjection": governance_projection,
            "approvalSubscription": approval_subscription,
            "receipts": receipts,
        }

    def _persist_record(
        self,
        *,
        record_kind: RecordKind,
        record_id: str,
        payload: GovernanceRecord,
        doc_id: str,
        metadata: dict[str, Any],
        label: str,
        summary: str,
    ) -> str:
        """Persist one stable-id record node in the governance store namespace."""
        node_id = self._record_node_id(record_kind, record_id, payload)
        if record_kind in STRUCTURED_RECORD_KINDS:
            return node_id
        entity_type = str(metadata.get("entity_type") or STORE_RECORD_ENTITY)
        node = governance_node(
            node_id=node_id,
            label=label,
            summary=summary,
            doc_id=doc_id,
            metadata={
                "entity_type": entity_type,
                "record_kind": record_kind,
                "record_id": record_id,
                **{k: v for k, v in metadata.items() if v is not None},
            },
            # Store the full record as JSON because substrate node properties only
            # support primitive-friendly values; metadata remains the index layer.
            properties={
                "payloadJson": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            },
        )
        self.conversation_engine.write.add_node(node)
        return node_id

    def _clear_projection_namespace(self) -> None:
        """Clear the bridge governance named-projection namespace."""
        meta = getattr(self.conversation_engine, "meta_sqlite", None)
        clearer = getattr(meta, "clear_projection_namespace", None)
        if callable(clearer):
            clearer(BRIDGE_GOVERNANCE_PROJECTION_NAMESPACE)

    def _project_latest_record(
        self,
        record_kind: StructuredRecordKind,
        record_id: str,
        payload: GovernanceRecord,
    ) -> None:
        """Update the latest-state projection from an append-only record fact."""
        meta = getattr(self.conversation_engine, "meta_sqlite", None)
        replacer = getattr(meta, "replace_named_projection", None)
        if not callable(replacer):
            if record_kind in {"approval", "gateway_approval"}:
                _approval_debug(
                    "project_latest_record:skip_no_replacer",
                    recordKind=record_kind,
                    recordId=record_id,
                )
            return
        replacer(
            BRIDGE_GOVERNANCE_PROJECTION_NAMESPACE,
            self._projection_key(record_kind, record_id),
            dict(payload),
            last_authoritative_seq=self._projection_seq_for_record(payload),
            last_materialized_seq=self._projection_seq_for_record(payload),
            projection_schema_version=1,
            materialization_status="ready",
        )
        if record_kind in {"approval", "gateway_approval"}:
            _approval_debug(
                "project_latest_record:ok",
                recordKind=record_kind,
                recordId=record_id,
                projectionKey=self._projection_key(record_kind, record_id),
            )

    def _projection_seq_for_record(self, payload: GovernanceRecord) -> int:
        """Best-effort seq watermark for bridge governance projection rows."""
        if not isinstance(payload, dict):
            return 0
        governance_call_id = payload.get("governanceCallId")
        if not isinstance(governance_call_id, str) or not governance_call_id:
            return 0
        meta = getattr(self.conversation_engine, "meta_sqlite", None)
        current_scoped_seq = getattr(meta, "current_scoped_seq", None)
        if not callable(current_scoped_seq):
            return 0
        try:
            return int(current_scoped_seq(f"governance:{governance_call_id}") or 0)
        except Exception:
            return 0

    @staticmethod
    def _projection_key(record_kind: StructuredRecordKind, record_id: str) -> str:
        return f"{record_kind}:{record_id}"

    @staticmethod
    def _projection_key_prefix(record_kind: StructuredRecordKind) -> str:
        return f"{record_kind}:"

    @staticmethod
    def _sorted_records(
        records: Sequence[CanonicalGovernanceEventRow] | Sequence[IntegrationReceiptRow],
        *,
        keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        def sort_key(record: dict[str, Any]) -> tuple:
            if "eventType" in record:
                event_rank = {
                    "governance.tool_call_observed.v1": "01",
                    "governance.decision_recorded.v1": "02",
                    "governance.approval_requested.v1": "03",
                    "governance.execution_suspended.v1": "04",
                    "governance.approval_resolved.v1": "05",
                    "governance.execution_resumed.v1": "06",
                    "governance.execution_denied.v1": "07",
                    "governance.result_recorded.v1": "08",
                    "governance.completed.v1": "09",
                    "governance.tool_call_completed.v1": "10",
                }.get(str(record.get("eventType") or ""), "99")
            else:
                event_rank = "00"
            return (event_rank,) + tuple(str(record.get(key) or "") for key in keys)

        return sorted(records, key=sort_key)

    @staticmethod
    def _record_node_id(record_kind: RecordKind, record_id: str, payload: GovernanceRecord) -> str:
        """Return an append-only record node id for projection-like records.

        Canonical events and receipts already have unique fact ids, so their
        stable ids are safe. Projection-like records get a content hash suffix
        so new states append rather than pretending to overwrite graph truth.
        """
        if record_kind in {"event", "receipt"}:
            return f"govstore|{record_kind}|{record_id}"
        digest = hashlib.sha1(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        return f"govstore|{record_kind}|{record_id}|{digest}"

    def _record_id_key(self, record_kind: RecordKind) -> str:
        return {
            "event": "eventId",
            "receipt": "receiptId",
            "approval": "approvalRequestId",
            "gateway_approval": "gatewayApprovalId",
            "workflow_run": "governanceCallId",
            "projection": "governanceCallId",
            "approval_subscription": "kind",
        }.get(record_kind, "id")

    @overload
    def _load_records(self, record_kind: Literal["event"]) -> list[CanonicalGovernanceEventRow]: ...

    @overload
    def _load_records(self, record_kind: Literal["receipt"]) -> list[IntegrationReceiptRow]: ...

    @overload
    def _load_records(self, record_kind: StructuredRecordKind) -> dict[str, GovernanceRecord]: ...

    def _load_records(
        self,
        record_kind: RecordKind,
    ) -> list[CanonicalGovernanceEventRow] | list[IntegrationReceiptRow] | dict[str, GovernanceRecord]:
        """Load one durable record collection from graph-native store nodes."""
        if record_kind in STRUCTURED_RECORD_KINDS:
            projected_records = self._load_projected_records(record_kind)
            if projected_records:
                if record_kind in {"approval", "gateway_approval"}:
                    _approval_debug(
                        "load_records:from_projection",
                        recordKind=record_kind,
                        count=len(projected_records),
                    )
                return projected_records
        graph_records = self._load_graph_records(record_kind)
        if record_kind in STRUCTURED_RECORD_KINDS and isinstance(graph_records, dict) and graph_records:
            for projected_id, projected_record in graph_records.items():
                if isinstance(projected_record, dict):
                    self._project_latest_record(record_kind, projected_id, projected_record)
            projected_records = self._load_projected_records(record_kind)
            if projected_records:
                if record_kind in {"approval", "gateway_approval"}:
                    _approval_debug(
                        "load_records:from_graph_then_project",
                        recordKind=record_kind,
                        graphCount=len(graph_records),
                        projectedCount=len(projected_records),
                    )
                return projected_records
        if graph_records is not None:
            if record_kind in {"approval", "gateway_approval"} and isinstance(graph_records, dict):
                _approval_debug(
                    "load_records:graph_only",
                    recordKind=record_kind,
                    graphCount=len(graph_records),
                )
            return graph_records
        if record_kind in {"event", "receipt"}:
            return []
        if record_kind in {"approval", "gateway_approval"}:
            _approval_debug(
                "load_records:empty",
                recordKind=record_kind,
            )
        return {}

    def _load_projected_records(
        self,
        record_kind: StructuredRecordKind,
    ) -> dict[str, GovernanceRecord]:
        """Load the latest-state projection from the generic named-projection store."""
        meta = getattr(self.conversation_engine, "meta_sqlite", None)
        lister = getattr(meta, "list_named_projections", None)
        if not callable(lister):
            return {}
        projected: dict[str, GovernanceRecord] = {}
        for row in lister(BRIDGE_GOVERNANCE_PROJECTION_NAMESPACE) or []:
            if not isinstance(row, dict):
                continue
            key = row.get("key")
            if not isinstance(key, str) or not key.startswith(self._projection_key_prefix(record_kind)):
                continue
            record_id = key[len(self._projection_key_prefix(record_kind)) :]
            if not record_id:
                continue
            payload = row.get("payload")
            if isinstance(payload, dict):
                projected[record_id] = payload
        if record_kind in {"approval", "gateway_approval"}:
            _approval_debug(
                "load_projected_records",
                recordKind=record_kind,
                count=len(projected),
                sampleIds=list(projected.keys())[:5],
            )
        return projected

    def _load_graph_records(
        self,
        record_kind: RecordKind,
    ) -> list[CanonicalGovernanceEventRow] | list[IntegrationReceiptRow] | dict[str, GovernanceRecord] | None:
        """Load durable records from graph-native store nodes when available."""

        read = getattr(self.conversation_engine, "read", None)
        if read is None or not hasattr(read, "get_nodes"):
            return None

        try:
            nodes = read.get_nodes(  # type: ignore[call-arg]
                where={
                    "record_kind": record_kind
                },
                node_type=Node,
                limit=20_000,
            )
        except Exception:
            return None

        decoded_records: list[dict[str, Any]] = []
        for node in nodes or []:
            properties = getattr(node, "properties", {}) or {}
            payload_json = properties.get("payloadJson")
            if not isinstance(payload_json, str):
                continue
            try:
                payload = json.loads(payload_json)
            except Exception:
                continue
            if isinstance(payload, dict):
                decoded_records.append(payload)

        if record_kind in {"event", "receipt"}:
            return decoded_records

        if record_kind == "approval_subscription":
            if not decoded_records:
                return {}
            merged_subscription: dict[str, Any] = {}
            for record in decoded_records:
                merged_subscription.update(record)
            return merged_subscription

        id_key = self._record_id_key(record_kind)
        indexed: dict[str, GovernanceRecord] = {}
        for record in decoded_records:
            record_id = record.get(id_key)
            if isinstance(record_id, str):
                current = indexed.get(record_id)
                if isinstance(current, dict):
                    indexed[record_id] = self._merge_record_payloads(current, record)
                else:
                    indexed[record_id] = record
        return indexed

    def _merge_record_payloads(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        """Merge duplicate persisted records without depending on backend read order."""
        merged = dict(current)
        for key, incoming_value in incoming.items():
            if key not in merged:
                merged[key] = incoming_value
                continue
            current_value = merged[key]
            merged[key] = self._merge_record_value(key, current_value, incoming_value)
        return merged

    def _merge_record_value(self, key: str, current_value: Any, incoming_value: Any) -> Any:
        """Prefer the richer non-empty value when duplicate records disagree."""
        if isinstance(current_value, dict) and isinstance(incoming_value, dict):
            return self._merge_record_payloads(current_value, incoming_value)
        if self._is_empty_record_value(current_value):
            return incoming_value
        if self._is_empty_record_value(incoming_value):
            return current_value
        if key in {"ts", "createdAtMs", "expiresAtMs", "lastRequestedEventAt", "lastResolvedEventAt", "lastStatusAt"}:
            if isinstance(current_value, (int, float)) and isinstance(incoming_value, (int, float)):
                return max(current_value, incoming_value)
        if key in {"status", "decision"}:
            current_rank = self._resolution_rank(current_value)
            incoming_rank = self._resolution_rank(incoming_value)
            return incoming_value if incoming_rank >= current_rank else current_value
        return current_value

    @staticmethod
    def _is_empty_record_value(value: Any) -> bool:
        return value is None or value == "" or value == {} or value == []

    @staticmethod
    def _resolution_rank(value: Any) -> int:
        if not isinstance(value, str):
            return 0
        normalized = value.strip().lower()
        return {
            "pending": 0,
            "resolved": 1,
            "allow": 2,
            "allow-once": 2,
            "allow_once": 2,
            "deny": 2,
            "block": 2,
            "rejected": 2,
        }.get(normalized, 1 if normalized else 0)

    @staticmethod
    def _event_entity_type(event_type: str) -> str:
        return SEMANTIC_EVENT_ENTITY_TYPES.get(event_type, GENERIC_EVENT_ENTITY_TYPE)

    def _persist_semantic_event_relations(
        self,
        governance_call_id: str,
        event_record: CanonicalGovernanceEventRow,
        *,
        event_node_id: str,
    ) -> None:
        event_type = str(event_record["eventType"])
        event_id = str(event_record["eventId"])
        subject = event_record.get("subject")
        subject_data = subject if isinstance(subject, dict) else {}

        if event_type == "governance.decision_recorded.v1":
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_decided",
                    summary="Proposal received a governance decision",
                )
            return

        if event_type == "governance.approval_requested.v1":
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_requires_approval",
                    summary="Decision requires approval",
                )
            return

        if event_type == "governance.execution_suspended.v1":
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_suspended_for_approval",
                    summary="Approval request suspended execution",
                )
            return

        if event_type == "governance.approval_resolved.v1":
            approval_request_id = subject_data.get("approvalRequestId")
            if isinstance(approval_request_id, str) and approval_request_id:
                predecessor_event_id = self._find_event_id(
                    governance_call_id=governance_call_id,
                    event_type="governance.execution_suspended.v1",
                    approval_request_id=approval_request_id,
                )
                if predecessor_event_id is None:
                    predecessor_event_id = self._find_event_id(
                        governance_call_id=governance_call_id,
                        event_type="governance.approval_requested.v1",
                        approval_request_id=approval_request_id,
                    )
                if predecessor_event_id is not None:
                    self._link_semantic_events(
                        governance_call_id=governance_call_id,
                        source_event_id=predecessor_event_id,
                        target_event_id=event_id,
                        relation="governance_resolved_as",
                        summary="Approval request was resolved",
                    )
            return

        if event_type in {"governance.execution_resumed.v1", "governance.execution_denied.v1"}:
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_resulted_in",
                    summary="Approval resolution produced the governance result",
                )
            return

        if event_type == "governance.result_recorded.v1":
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_result_recorded_as",
                    summary="Governance result was recorded",
                )
            return

        if event_type == "governance.completed.v1":
            predecessor_event_id = event_record.get("causationId")
            if isinstance(predecessor_event_id, str) and predecessor_event_id:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="governance_completed",
                    summary="Governance flow completed",
                )
            return

        if event_type == "governance.tool_call_completed.v1":
            predecessor_event_id = self._find_event_id(
                governance_call_id=governance_call_id,
                event_type="governance.completed.v1",
            )
            if predecessor_event_id is None:
                predecessor_event_id = self._find_event_id(
                    governance_call_id=governance_call_id,
                    event_type="governance.execution_resumed.v1",
                )
            if predecessor_event_id is None:
                predecessor_event_id = self._find_event_id(
                    governance_call_id=governance_call_id,
                    event_type="governance.decision_recorded.v1",
                )
            if predecessor_event_id is not None:
                self._link_semantic_events(
                    governance_call_id=governance_call_id,
                    source_event_id=predecessor_event_id,
                    target_event_id=event_id,
                    relation="tool_execution_completed_as",
                    summary="Tool execution finished after governance completion",
                )

    def _link_matching_receipts(
        self,
        governance_call_id: str,
        event_record: CanonicalGovernanceEventRow,
        *,
        event_node_id: str,
    ) -> None:
        event_type = str(event_record.get("eventType") or "")
        for receipt in self.list_records("receipt"):
            receipt_id = receipt.get("receiptId")
            if not isinstance(receipt_id, str):
                continue
            if self._receipt_matches_event(governance_call_id, receipt, event_record, event_type=event_type):
                receipt_node_id = self._record_node_id("receipt", receipt_id, {})
                self.conversation_engine.write.add_edge(
                    governance_edge(
                        edge_id=f"govreceipt|{governance_call_id}|{receipt_id}|{event_node_id}",
                        source_id=receipt_node_id,
                        target_id=event_node_id,
                        relation="receipt_for",
                        label="receipt_for",
                        summary=f"Receipt {receipt_id} captured source input for {event_type}",
                        doc_id=STORE_DOC_IDS["receipts"],
                        metadata={
                            "entity_type": "governance_edge",
                            "governance_call_id": governance_call_id,
                            "receipt_id": receipt_id,
                            "event_type": event_type,
                        },
                    )
                )

    def _receipt_matches_event(
        self,
        governance_call_id: str,
        receipt: IntegrationReceiptRow,
        event_record: CanonicalGovernanceEventRow,
        *,
        event_type: str,
    ) -> bool:
        source_event_type = str(receipt.get("sourceEventType") or "")
        if source_event_type == "before_tool_call" and event_type == "governance.tool_call_observed.v1":
            return self._receipt_governance_call_id(receipt) == governance_call_id
        if (
            source_event_type == "after_tool_call"
            and event_type == "governance.execution_suspended.v1"
            and self._receipt_is_approval_pending_after_tool_call(receipt)
        ):
            return self._receipt_governance_call_id(receipt) == governance_call_id
        if source_event_type == "after_tool_call" and event_type == "governance.tool_call_completed.v1":
            return self._receipt_governance_call_id(receipt) == governance_call_id
        if source_event_type == "approval_resolution" and event_type == "governance.approval_resolved.v1":
            receipt_payload = receipt.get("payload")
            payload_data = receipt_payload if isinstance(receipt_payload, dict) else {}
            subject = event_record.get("subject")
            subject_data = subject if isinstance(subject, dict) else {}
            return payload_data.get("approvalId") == subject_data.get("approvalRequestId")
        return False

    @staticmethod
    def _receipt_governance_call_id(receipt: IntegrationReceiptRow) -> str | None:
        payload = receipt.get("payload")
        if not isinstance(payload, dict):
            return None
        raw_event = payload.get("rawEvent")
        raw_event_data = raw_event if isinstance(raw_event, dict) else {}
        return stable_governance_call_id(
            [
                GovernanceService._as_optional_str(payload.get("pluginId")),
                GovernanceService._as_optional_str(payload.get("sessionId")),
                GovernanceService._as_optional_str(payload.get("toolName")),
                GovernanceService._as_optional_str(raw_event_data.get("runId")),
                GovernanceService._as_optional_str(raw_event_data.get("toolCallId")),
            ]
        )

    @staticmethod
    def _receipt_is_approval_pending_after_tool_call(receipt: IntegrationReceiptRow) -> bool:
        payload = receipt.get("payload")
        if not isinstance(payload, dict):
            return False
        result = payload.get("result")
        if not isinstance(result, dict):
            return False
        details = result.get("details")
        if not isinstance(details, dict):
            return False
        status = details.get("status")
        if not isinstance(status, str):
            return False
        return status.strip().lower().replace("_", "-") == "approval-pending"

    @staticmethod
    def _as_optional_str(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _link_semantic_events(
        self,
        *,
        governance_call_id: str,
        source_event_id: str,
        target_event_id: str,
        relation: str,
        summary: str,
    ) -> None:
        source_node_id = self._record_node_id("event", source_event_id, {})
        target_node_id = self._record_node_id("event", target_event_id, {})
        if not self._node_exists(source_node_id) or not self._node_exists(target_node_id):
            return
        edge_id = f"govevent|{governance_call_id}|edge|{source_event_id}->{target_event_id}|{relation}"
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=edge_id,
                source_id=source_node_id,
                target_id=target_node_id,
                relation=relation,
                label=relation,
                summary=summary,
                doc_id=BACKBONE_DOC_ID,
                metadata={
                    "entity_type": "governance_edge",
                    "governance_call_id": governance_call_id,
                    "source_event_id": source_event_id,
                    "target_event_id": target_event_id,
                },
            )
        )

    def _reconcile_semantic_event_relations(self, governance_call_id: str) -> None:
        for record in self.list_records("event"):
            subject = record.get("subject")
            subject_data = subject if isinstance(subject, dict) else {}
            if subject_data.get("governanceCallId") != governance_call_id:
                continue
            event_id = record.get("eventId")
            if not isinstance(event_id, str) or not event_id:
                continue
            self._persist_semantic_event_relations(
                governance_call_id,
                record,
                event_node_id=self._record_node_id("event", event_id, {}),
            )

    def _node_exists(self, node_id: str) -> bool:
        backend = getattr(self.conversation_engine, "backend", None)
        if backend is None or not hasattr(backend, "node_get"):
            return True
        try:
            got = backend.node_get(ids=[node_id], include=[])
        except Exception:
            return False
        ids = got.get("ids") if isinstance(got, dict) else None
        return bool(ids and ids[0] == node_id)

    def _find_event_id(
        self,
        *,
        governance_call_id: str,
        event_type: str,
        approval_request_id: str | None = None,
    ) -> str | None:
        matches: list[tuple[str, str]] = []
        for record in self.list_records("event"):
            if record.get("eventType") != event_type:
                continue
            subject = record.get("subject")
            subject_data = subject if isinstance(subject, dict) else {}
            if subject_data.get("governanceCallId") != governance_call_id:
                continue
            if approval_request_id is not None and subject_data.get("approvalRequestId") != approval_request_id:
                continue
            event_id = record.get("eventId")
            recorded_at = str(record.get("recordedAt") or record.get("occurredAt") or "")
            if isinstance(event_id, str):
                matches.append((recorded_at, event_id))
        if not matches:
            return None
        matches.sort()
        return matches[-1][1]

    def _persist_backbone_for_event(
        self,
        governance_call_id: str,
        event_record: CanonicalGovernanceEventRow,
    ) -> tuple[str | None, str | None]:
        """Persist the operator-facing backbone chain and return the event anchor."""
        event_type = str(event_record["eventType"])
        if event_type == "governance.tool_call_observed.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_input", "input_received")
            return "input_received", "governance_observed_at"

        if event_type == "governance.decision_recorded.v1":
            disposition = str(event_record.get("data", {}).get("disposition") or "")
            step = {
                "allow": "policy_approved",
                "block": "policy_rejected",
                "require_approval": "require_approval",
            }.get(disposition, "decision_recorded")
            self._ensure_backbone_transition(governance_call_id, "input_received", step)
            return step, "governance_decision_at"

        if event_type == "governance.approval_requested.v1":
            self._ensure_backbone_transition(governance_call_id, "require_approval", "waiting_approval")
            return "waiting_approval", "governance_approval_requested_at"

        if event_type == "governance.execution_suspended.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_approval", "approval_suspended")
            return "approval_suspended", "governance_suspended_at"

        if event_type == "governance.approval_resolved.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_suspended", "approval_received")
            return "approval_received", "governance_approval_resolved_at"

        if event_type == "governance.execution_resumed.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_received", "governance_resolved")
            return "governance_resolved", "governance_resumed_at"

        if event_type == "governance.execution_denied.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_received", "governance_resolved")
            return "governance_resolved", "governance_denied_at"

        if event_type == "governance.result_recorded.v1":
            final_disposition = str(event_record.get("data", {}).get("finalDisposition") or "")
            if final_disposition == "allow":
                predecessor = "approval_received" if self._find_event_id(
                    governance_call_id=governance_call_id,
                    event_type="governance.approval_resolved.v1",
                ) else "policy_approved"
                self._ensure_backbone_transition(governance_call_id, predecessor, "governance_resolved")
            else:
                predecessor = "approval_received" if self._find_event_id(
                    governance_call_id=governance_call_id,
                    event_type="governance.approval_resolved.v1",
                ) else "policy_rejected"
                self._ensure_backbone_transition(governance_call_id, predecessor, "governance_resolved")
            return "governance_resolved", "governance_result_recorded_at"

        if event_type == "governance.completed.v1":
            final_disposition = str(event_record.get("data", {}).get("finalDisposition") or "")
            if final_disposition == "allow":
                self._ensure_backbone_transition(governance_call_id, "governance_resolved", "waiting_output")
                return "governance_resolved", "governance_completed_at"
            self._ensure_backbone_transition(governance_call_id, "governance_resolved", "run_completed")
            return "run_completed", "governance_completed_at"

        if event_type == "governance.tool_call_completed.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_output", "output_received")
            self._ensure_backbone_transition(governance_call_id, "output_received", "run_completed")
            return "run_completed", "tool_execution_completed_at"
        return None, None

    def _ensure_backbone_transition(self, governance_call_id: str, from_step: str, to_step: str) -> None:
        from_id = self._ensure_backbone_step(governance_call_id, from_step)
        to_id = self._ensure_backbone_step(governance_call_id, to_step)
        edge_id = f"govbackbone|{governance_call_id}|edge|{from_step}->{to_step}"
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=edge_id,
                source_id=from_id,
                target_id=to_id,
                relation="next",
                label="next",
                summary=f"{from_step} -> {to_step}",
                doc_id=BACKBONE_DOC_ID,
                metadata={
                    "entity_type": "governance_backbone_edge",
                    "governance_call_id": governance_call_id,
                    "from_step": from_step,
                    "to_step": to_step,
                },
            )
        )

    def _ensure_backbone_step(self, governance_call_id: str, step: str) -> str:
        node_id = f"govbackbone|{governance_call_id}|{step}"
        backend = getattr(self.conversation_engine, "backend", None)
        if backend is not None and hasattr(backend, "node_get"):
            try:
                got = backend.node_get(ids=[node_id], include=[])
            except Exception:
                got = None
            if isinstance(got, dict) and got.get("ids"):
                return node_id
        self.conversation_engine.write.add_node(
            governance_node(
                node_id=node_id,
                label=step.replace("_", " "),
                summary=f"Governance backbone step {step}",
                doc_id=BACKBONE_DOC_ID,
                metadata={
                    "entity_type": BACKBONE_ENTITY,
                    "governance_call_id": governance_call_id,
                    "step": step,
                },
                properties={"governanceCallId": governance_call_id, "step": step},
            )
        )
        return node_id

    def _link_event_to_backbone(
        self,
        governance_call_id: str,
        event_node_id: str,
        backbone_step: str,
        relation: str,
    ) -> None:
        step_node_id = self._ensure_backbone_step(governance_call_id, backbone_step)
        edge_id = f"govbackbone|{governance_call_id}|event|{backbone_step}|{event_node_id}"
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=edge_id,
                source_id=step_node_id,
                target_id=event_node_id,
                relation=relation,
                label=relation,
                summary=f"Backbone step {backbone_step} references {event_node_id}",
                doc_id=BACKBONE_DOC_ID,
                metadata={
                    "entity_type": "governance_backbone_side_event",
                    "governance_call_id": governance_call_id,
                    "step": backbone_step,
                },
            )
        )
