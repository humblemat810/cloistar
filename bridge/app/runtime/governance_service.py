from __future__ import annotations

"""Durable governance persistence facade.

This module mirrors the role that ``ConversationService`` plays for the chat
domain: one service-level boundary over graph writes, durable row materializing,
and operator/debug queries.

The service intentionally reuses core Kogwistar substrate models instead of
introducing a separate governance-only storage primitive. Governance semantics
come from metadata, deterministic ids, and backbone/link relations.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence, TypeAlias, overload

from ..domain.governance_models import (
    ApprovalRow,
    ApprovalSubscriptionStatusRow,
    GatewayApprovalRow,
    GovernanceProjectionRow,
    IntegrationReceipt,
    WorkflowRunRow,
)
from .governance_graph import governance_edge, governance_grounding, governance_node


STORE_ROW_ENTITY = "governance_store_row"
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
_SERVICE_CACHE: dict[tuple[int, int | None], "GovernanceService"] = {}
RowKind: TypeAlias = Literal[
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
DurableGovernanceRow: TypeAlias = (
    CanonicalGovernanceEventRow
    | IntegrationReceiptRow
    | ApprovalRow
    | GatewayApprovalRow
    | WorkflowRunRow
    | GovernanceProjectionRow
    | ApprovalSubscriptionStatusRow
)
StructuredRowKind: TypeAlias = Literal[
    "approval",
    "gateway_approval",
    "workflow_run",
    "projection",
    "approval_subscription",
]


class GraphWritePort(Protocol):
    def add_node(self, node: Any) -> Any: ...

    def add_edge(self, edge: Any) -> Any: ...


class GraphRollbackPort(Protocol):
    def rollback_document(self, doc_id: str) -> Any: ...


class GraphEnginePort(Protocol):
    persist_directory: str | None
    write: GraphWritePort
    rollback: GraphRollbackPort


@dataclass
class GovernanceService:
    """Service facade for durable governance state and debug projections."""

    conversation_engine: GraphEnginePort
    workflow_engine: GraphEnginePort | None = None
    store_dir: Path | None = None

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
        persist_root = None
        if workflow_engine is not None and getattr(workflow_engine, "persist_directory", None):
            persist_root = Path(str(workflow_engine.persist_directory)).parent
        elif getattr(conversation_engine, "persist_directory", None):
            persist_root = Path(str(conversation_engine.persist_directory)).parent
        store_dir = (persist_root or Path.cwd()) / "governance-store"
        service = cls(
            conversation_engine=conversation_engine,
            workflow_engine=workflow_engine,
            store_dir=store_dir,
        )
        _SERVICE_CACHE[cache_key] = service
        return service

    def reset_store(self) -> None:
        """Delete durable governance store documents used by tests and local runs."""
        for path in self._row_file_paths().values():
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for doc_id in STORE_RESET_DOC_IDS:
            try:
                self.conversation_engine.rollback.rollback_document(doc_id)
            except Exception:
                # Durable reset is best-effort; a missing doc is not an error.
                continue

    def persist_event_row(self, event_row: CanonicalGovernanceEventRow) -> CanonicalGovernanceEventRow:
        """Persist one canonical governance event row and attach it to the backbone."""
        event_id = str(event_row["eventId"])
        event_type = str(event_row["eventType"])
        governance_call_id = str(event_row["subject"]["governanceCallId"])
        node_id = self._persist_row(
            row_kind="event",
            row_id=event_id,
            payload=event_row,
            doc_id=STORE_DOC_IDS["events"],
            metadata={
                "event_type": event_type,
                "governance_call_id": governance_call_id,
            },
            label=event_type,
            summary=f"Canonical governance event {event_type}",
        )
        self._persist_backbone_for_event(governance_call_id, event_row, event_node_id=node_id)
        return dict(event_row)

    def persist_receipt_row(
        self,
        receipt_row: IntegrationReceiptRow | IntegrationReceipt,
    ) -> IntegrationReceiptRow:
        """Persist one integration receipt row."""
        receipt_data = dict(receipt_row)
        self._persist_row(
            row_kind="receipt",
            row_id=str(receipt_data["receiptId"]),
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

    def upsert_approval_row(self, approval_id: str, payload: ApprovalRow) -> ApprovalRow:
        """Persist one approval summary row with stable identity."""
        row: ApprovalRow = payload
        row["approvalRequestId"] = approval_id
        self._persist_row(
            row_kind="approval",
            row_id=approval_id,
            payload=row,
            doc_id=STORE_DOC_IDS["approvals"],
            metadata={
                "approval_request_id": approval_id,
                "governance_call_id": row.get("governanceCallId"),
                "tool_call_id": row.get("toolCallId"),
                "tool_name": row.get("toolName"),
                "status": row.get("status"),
                "gateway_approval_id": row.get("gatewayApprovalId"),
            },
            label=f"Approval {approval_id}",
            summary=f"Approval row for {row.get('toolName') or 'tool'}",
        )
        return row

    def upsert_gateway_approval_row(
        self,
        gateway_approval_id: str,
        payload: GatewayApprovalRow,
    ) -> GatewayApprovalRow:
        """Persist one gateway approval row with stable identity."""
        row: GatewayApprovalRow = payload
        row["gatewayApprovalId"] = gateway_approval_id
        request = row.get("request")
        request_data = request if isinstance(request, dict) else {}
        self._persist_row(
            row_kind="gateway_approval",
            row_id=gateway_approval_id,
            payload=row,
            doc_id=STORE_DOC_IDS["gateway_approvals"],
            metadata={
                "gateway_approval_id": gateway_approval_id,
                "tool_call_id": request_data.get("toolCallId"),
                "kind": row.get("kind"),
                "status": row.get("status"),
                "bridge_approval_id": row.get("bridgeApprovalId"),
            },
            label=f"Gateway approval {gateway_approval_id}",
            summary="OpenClaw gateway approval row",
        )
        return row

    def upsert_workflow_run_row(
        self,
        governance_call_id: str,
        payload: WorkflowRunRow,
    ) -> WorkflowRunRow:
        """Persist a workflow-run summary row keyed by governance call id."""
        row: WorkflowRunRow = payload
        row["governanceCallId"] = governance_call_id
        self._persist_row(
            row_kind="workflow_run",
            row_id=governance_call_id,
            payload=row,
            doc_id=STORE_DOC_IDS["workflow_runs"],
            metadata={
                "governance_call_id": governance_call_id,
                "workflow_id": row.get("workflowId"),
                "run_id": row.get("runId"),
                "status": row.get("status"),
                "decision": row.get("decision"),
                "final_disposition": row.get("finalDisposition"),
            },
            label=f"Workflow run {governance_call_id}",
            summary=f"Workflow summary for governance call {governance_call_id}",
        )
        return row

    def upsert_projection_row(
        self,
        governance_call_id: str,
        payload: GovernanceProjectionRow,
    ) -> GovernanceProjectionRow:
        """Persist a governance projection row keyed by governance call id."""
        row: GovernanceProjectionRow = payload
        row["governanceCallId"] = governance_call_id
        self._persist_row(
            row_kind="projection",
            row_id=governance_call_id,
            payload=row,
            doc_id=STORE_DOC_IDS["governance_projection"],
            metadata={
                "governance_call_id": governance_call_id,
                "proposal_node_id": row.get("proposalNodeId"),
                "decision_node_id": row.get("decisionNodeId"),
                "approval_node_id": row.get("approvalNodeId"),
                "resolution_node_id": row.get("resolutionNodeId"),
                "completion_node_id": row.get("completionNodeId"),
            },
            label=f"Projection {governance_call_id}",
            summary=f"Projection for governance call {governance_call_id}",
        )
        return row

    def upsert_approval_subscription_row(
        self,
        payload: ApprovalSubscriptionStatusRow,
    ) -> ApprovalSubscriptionStatusRow:
        """Persist the latest approval-listener subscription status."""
        row: ApprovalSubscriptionStatusRow = payload
        self._persist_row(
            row_kind="approval_subscription",
            row_id="latest",
            payload=row,
            doc_id=STORE_DOC_IDS["approval_subscription"],
            metadata={
                "enabled": row.get("enabled"),
                "started": row.get("started"),
                "connected": row.get("connected"),
                "last_error": row.get("lastError"),
            },
            label="Approval subscription status",
            summary="Latest gateway approval listener status",
        )
        return row

    @overload
    def get_row(self, row_kind: Literal["event"], row_id: str) -> CanonicalGovernanceEventRow | None: ...

    @overload
    def get_row(self, row_kind: Literal["receipt"], row_id: str) -> IntegrationReceiptRow | None: ...

    @overload
    def get_row(self, row_kind: Literal["approval"], row_id: str) -> ApprovalRow | None: ...

    @overload
    def get_row(self, row_kind: Literal["gateway_approval"], row_id: str) -> GatewayApprovalRow | None: ...

    @overload
    def get_row(self, row_kind: Literal["workflow_run"], row_id: str) -> WorkflowRunRow | None: ...

    @overload
    def get_row(self, row_kind: Literal["projection"], row_id: str) -> GovernanceProjectionRow | None: ...

    @overload
    def get_row(
        self,
        row_kind: Literal["approval_subscription"],
        row_id: str,
    ) -> ApprovalSubscriptionStatusRow | None: ...

    def get_row(self, row_kind: RowKind, row_id: str) -> DurableGovernanceRow | None:
        """Return one persisted row payload by kind and stable row id."""
        rows = self._load_rows(row_kind)
        if isinstance(rows, dict):
            row = rows.get(row_id)
            return dict(row) if isinstance(row, dict) else None
        for row in rows:
            if isinstance(row, dict) and str(row.get(self._row_id_key(row_kind), "")) == row_id:
                return dict(row)
        return None

    @overload
    def list_rows(self, row_kind: Literal["event"]) -> list[CanonicalGovernanceEventRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["receipt"]) -> list[IntegrationReceiptRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["approval"]) -> list[ApprovalRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["gateway_approval"]) -> list[GatewayApprovalRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["workflow_run"]) -> list[WorkflowRunRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["projection"]) -> list[GovernanceProjectionRow]: ...

    @overload
    def list_rows(self, row_kind: Literal["approval_subscription"]) -> list[ApprovalSubscriptionStatusRow]: ...

    def list_rows(self, row_kind: RowKind) -> Sequence[DurableGovernanceRow]:
        """Return all persisted rows for one logical row kind."""
        rows = self._load_rows(row_kind)
        if row_kind == "approval_subscription":
            return [dict(rows)] if isinstance(rows, dict) and rows else []
        if isinstance(rows, dict):
            return [dict(row) for row in rows.values() if isinstance(row, dict)]
        return [dict(row) for row in rows if isinstance(row, dict)]

    def count_matching_approvals(self, tool_name: str) -> int:
        """Count approvals for one tool from durable persisted rows."""
        return sum(1 for row in self.list_rows("approval") if row.get("toolName") == tool_name)

    def materialize_debug_snapshot(self) -> dict[str, Any]:
        """Build the bridge debug-state shape from durable row nodes."""
        events = self._sorted_rows(self.list_rows("event"), keys=("recordedAt", "occurredAt", "eventId"))
        receipts = self._sorted_rows(self.list_rows("receipt"), keys=("receivedAt", "receiptId"))
        approvals: dict[str, ApprovalRow] = {}
        for row in self.list_rows("approval"):
            approval_request_id = row.get("approvalRequestId")
            if isinstance(approval_request_id, str):
                approvals[approval_request_id] = row

        gateway_approvals: dict[str, GatewayApprovalRow] = {}
        for row in self.list_rows("gateway_approval"):
            gateway_approval_id = row.get("gatewayApprovalId")
            if isinstance(gateway_approval_id, str):
                gateway_approvals[gateway_approval_id] = row

        workflow_runs: dict[str, WorkflowRunRow] = {}
        for row in self.list_rows("workflow_run"):
            governance_call_id = row.get("governanceCallId")
            if isinstance(governance_call_id, str):
                workflow_runs[governance_call_id] = row

        governance_projection: dict[str, GovernanceProjectionRow] = {}
        for row in self.list_rows("projection"):
            governance_call_id = row.get("governanceCallId")
            if isinstance(governance_call_id, str):
                governance_projection[governance_call_id] = row

        subscription_rows = self.list_rows("approval_subscription")
        approval_subscription = subscription_rows[-1] if subscription_rows else {
            "enabled": False,
            "started": False,
            "connected": False,
            "lastError": None,
            "lastRequestedEventAt": None,
            "lastResolvedEventAt": None,
            "lastStatusAt": None,
        }
        return {
            "events": events,
            "approvals": approvals,
            "gatewayApprovals": gateway_approvals,
            "workflowRuns": workflow_runs,
            "governanceProjection": governance_projection,
            "approvalSubscription": approval_subscription,
            "receipts": receipts,
        }

    def _persist_row(
        self,
        *,
        row_kind: RowKind,
        row_id: str,
        payload: DurableGovernanceRow,
        doc_id: str,
        metadata: dict[str, Any],
        label: str,
        summary: str,
    ) -> str:
        """Persist one stable-id row node in the governance store namespace."""
        node_id = self._row_node_id(row_kind, row_id)
        node = governance_node(
            node_id=node_id,
            label=label,
            summary=summary,
            doc_id=doc_id,
            metadata={
                "entity_type": STORE_ROW_ENTITY,
                "row_kind": row_kind,
                "row_id": row_id,
                **{k: v for k, v in metadata.items() if v is not None},
            },
            # Store the full row as JSON because substrate node properties only
            # support primitive-friendly values; metadata remains the index layer.
            properties={
                "payloadJson": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            },
        )
        self.conversation_engine.write.add_node(node)
        self._write_row(row_kind=row_kind, row_id=row_id, payload=payload)
        return node_id

    @staticmethod
    def _sorted_rows(
        rows: Sequence[CanonicalGovernanceEventRow] | Sequence[IntegrationReceiptRow],
        *,
        keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        def sort_key(row: dict[str, Any]) -> tuple:
            if "eventType" in row:
                event_rank = {
                    "governance.tool_call_observed.v1": "01",
                    "governance.decision_recorded.v1": "02",
                    "governance.approval_requested.v1": "03",
                    "governance.execution_suspended.v1": "04",
                    "governance.approval_resolved.v1": "05",
                    "governance.execution_resumed.v1": "06",
                    "governance.execution_denied.v1": "07",
                    "governance.tool_call_completed.v1": "08",
                }.get(str(row.get("eventType") or ""), "99")
            else:
                event_rank = "00"
            return (event_rank,) + tuple(str(row.get(key) or "") for key in keys)

        return sorted(rows, key=sort_key)

    @staticmethod
    def _row_node_id(row_kind: RowKind, row_id: str) -> str:
        return f"govstore|{row_kind}|{row_id}"

    def _row_file_paths(self) -> dict[RowKind, Path]:
        """Return file locations for the durable JSON row collections."""
        store_dir = self.store_dir or (Path.cwd() / "governance-store")
        store_dir.mkdir(parents=True, exist_ok=True)
        return {
            "event": store_dir / "events.json",
            "receipt": store_dir / "receipts.json",
            "approval": store_dir / "approvals.json",
            "gateway_approval": store_dir / "gateway_approvals.json",
            "workflow_run": store_dir / "workflow_runs.json",
            "projection": store_dir / "projections.json",
            "approval_subscription": store_dir / "approval_subscription.json",
        }

    def _row_id_key(self, row_kind: RowKind) -> str:
        return {
            "event": "eventId",
            "receipt": "receiptId",
            "approval": "approvalRequestId",
            "gateway_approval": "gatewayApprovalId",
            "workflow_run": "governanceCallId",
            "projection": "governanceCallId",
            "approval_subscription": "kind",
        }.get(row_kind, "id")

    @overload
    def _load_rows(self, row_kind: Literal["event"]) -> list[CanonicalGovernanceEventRow]: ...

    @overload
    def _load_rows(self, row_kind: Literal["receipt"]) -> list[IntegrationReceiptRow]: ...

    @overload
    def _load_rows(self, row_kind: StructuredRowKind) -> dict[str, DurableGovernanceRow]: ...

    def _load_rows(
        self,
        row_kind: RowKind,
    ) -> list[CanonicalGovernanceEventRow] | list[IntegrationReceiptRow] | dict[str, DurableGovernanceRow]:
        """Load one durable row collection from JSON on disk."""
        path = self._row_file_paths()[row_kind]
        if not path.exists():
            if row_kind in {"event", "receipt"}:
                return []
            return {}
        data = json.loads(path.read_text())
        return data if isinstance(data, (list, dict)) else ([] if row_kind in {"event", "receipt"} else {})

    def _write_row(self, *, row_kind: RowKind, row_id: str, payload: DurableGovernanceRow) -> None:
        """Write one durable row into its JSON collection."""
        current = self._load_rows(row_kind)
        if isinstance(current, list):
            id_key = self._row_id_key(row_kind)
            replaced = False
            for index, row in enumerate(current):
                if isinstance(row, dict) and str(row.get(id_key, "")) == row_id:
                    current[index] = dict(payload)
                    replaced = True
                    break
            if not replaced:
                current.append(dict(payload))
            self._row_file_paths()[row_kind].write_text(json.dumps(current, indent=2, sort_keys=True))
            return

        if row_kind == "approval_subscription":
            self._row_file_paths()[row_kind].write_text(json.dumps(dict(payload), indent=2, sort_keys=True))
            return

        current[row_id] = dict(payload)
        self._row_file_paths()[row_kind].write_text(json.dumps(current, indent=2, sort_keys=True))

    def _persist_backbone_for_event(
        self,
        governance_call_id: str,
        event_row: CanonicalGovernanceEventRow,
        *,
        event_node_id: str,
    ) -> None:
        """Persist the operator-facing backbone chain and link the event to its anchor."""
        event_type = str(event_row["eventType"])
        if event_type == "governance.tool_call_observed.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_input", "input_received")
            self._link_event_to_backbone(governance_call_id, event_node_id, "input_received", "governance_observed_at")
            return

        if event_type == "governance.decision_recorded.v1":
            disposition = str(event_row.get("data", {}).get("disposition") or "")
            step = {
                "allow": "policy_approved",
                "block": "policy_rejected",
                "require_approval": "require_approval",
            }.get(disposition, "decision_recorded")
            self._ensure_backbone_transition(governance_call_id, "input_received", step)
            self._link_event_to_backbone(governance_call_id, event_node_id, step, "governance_decision_at")
            return

        if event_type == "governance.approval_requested.v1":
            self._ensure_backbone_transition(governance_call_id, "require_approval", "waiting_approval")
            self._link_event_to_backbone(governance_call_id, event_node_id, "waiting_approval", "governance_approval_requested_at")
            return

        if event_type == "governance.execution_suspended.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_approval", "approval_suspended")
            self._link_event_to_backbone(governance_call_id, event_node_id, "approval_suspended", "governance_suspended_at")
            return

        if event_type == "governance.approval_resolved.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_suspended", "approval_received")
            self._link_event_to_backbone(governance_call_id, event_node_id, "approval_received", "governance_approval_resolved_at")
            return

        if event_type == "governance.execution_resumed.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_received", "waiting_output")
            self._link_event_to_backbone(governance_call_id, event_node_id, "waiting_output", "governance_resumed_at")
            return

        if event_type == "governance.execution_denied.v1":
            self._ensure_backbone_transition(governance_call_id, "approval_received", "policy_rejected")
            self._link_event_to_backbone(governance_call_id, event_node_id, "policy_rejected", "governance_denied_at")
            return

        if event_type == "governance.tool_call_completed.v1":
            self._ensure_backbone_transition(governance_call_id, "waiting_output", "output_received")
            self._link_event_to_backbone(governance_call_id, event_node_id, "output_received", "governance_completed_at")

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
