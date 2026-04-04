from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence, cast
from uuid import uuid4

from kogwistar.engine_core.engine import GraphKnowledgeEngine
from kogwistar.runtime.models import RunSuccess
from kogwistar.runtime.runtime import WorkflowRuntime

from ..domain.governance_models import (
    ApprovalRow,
    GovernanceProjectionRow,
    PolicyEvaluation,
    ToolCallCompletedEvent,
    ToolCallObservedEvent,
    WorkflowRunRow,
)
from .governance_design import GOVERNANCE_WORKFLOW_ID, ensure_governance_workflow_design
from .governance_graph import governance_edge, governance_node, install_governance_scoped_seq_hooks
from .governance_resolvers import governance_resolver


class _ZeroEmbeddingFunction:
    """Deterministic tiny embedder compatible with real Chroma clients."""

    _name = "ZeroEmbedding"

    def name(self) -> str:
        return self._name

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        return [[0.001, 0.0010, 0.00010] for _ in input]

    def is_legacy(self) -> bool:
        return False


_ZERO_EMBEDDING_FUNCTION = _ZeroEmbeddingFunction()


@dataclass
class GovernanceRuntimeDecision:
    evaluation: PolicyEvaluation
    workflow: WorkflowRunRow
    projection: GovernanceProjectionRow


@dataclass
class GovernanceRuntimeResume:
    workflow: WorkflowRunRow
    projection: GovernanceProjectionRow


class GovernanceRuntimeHost:
    def __init__(self, *, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or self._default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_id = GOVERNANCE_WORKFLOW_ID
        self.workflow_engine = GraphKnowledgeEngine(
            persist_directory=str(self.data_dir / "workflow"),
            kg_graph_type="workflow",
            embedding_function=_ZERO_EMBEDDING_FUNCTION,
        )
        self.conversation_engine = GraphKnowledgeEngine(
            persist_directory=str(self.data_dir / "conversation"),
            kg_graph_type="conversation",
            embedding_function=_ZERO_EMBEDDING_FUNCTION,
        )
        # Governance keeps its own append-only branch ordering, separate from the
        # chat-domain conversation sequencing policy.
        install_governance_scoped_seq_hooks(self.conversation_engine)
        ensure_governance_workflow_design(self.workflow_engine, workflow_id=self.workflow_id)
        self.runtime = WorkflowRuntime(
            workflow_engine=self.workflow_engine,
            conversation_engine=self.conversation_engine,
            step_resolver=governance_resolver,
            predicate_registry={},
            checkpoint_every_n_steps=1,
            max_workers=1,
        )

    @staticmethod
    def _default_data_dir() -> Path:
        configured = os.getenv("KOGWISTAR_RUNTIME_DATA_DIR")
        if configured:
            return Path(configured)
        return Path(tempfile.mkdtemp(prefix="kogwistar-bridge-runtime-"))

    def evaluate_proposal(
        self,
        observed_event: ToolCallObservedEvent,
        *,
        policy_evaluator,
        store,
    ) -> GovernanceRuntimeDecision:
        governance_call_id = observed_event.subject.governanceCallId
        conversation_id = f"gov:{observed_event.correlationId or governance_call_id}"
        turn_node_id = f"gov-turn:{governance_call_id}"
        run_id = f"govrun:{uuid4()}"

        result = self.runtime.run(
            workflow_id=self.workflow_id,
            conversation_id=conversation_id,
            turn_node_id=turn_node_id,
            run_id=run_id,
            initial_state={
                "conversation_id": conversation_id,
                "user_id": observed_event.data.sourceRef.pluginId or "openclaw",
                "turn_node_id": turn_node_id,
                "role": "system",
                "user_text": f"{observed_event.data.tool.name} proposal",
                "governance_call_id": governance_call_id,
                "tool_name": observed_event.data.tool.name,
                "tool_params": observed_event.data.tool.params,
                "proposal": observed_event.model_dump(mode="json"),
                "_deps": {
                    "conversation_engine": self.conversation_engine,
                    "workflow_engine": self.workflow_engine,
                    "policy_evaluator": policy_evaluator,
                    "store": store,
                },
            },
        )
        evaluation = PolicyEvaluation.model_validate(result.final_state["policy_evaluation"])
        projection = self._projection_from_state(result.final_state)
        workflow = self._workflow_snapshot(
            governance_call_id=governance_call_id,
            run_id=run_id,
            conversation_id=conversation_id,
            turn_node_id=turn_node_id,
            final_state=result.final_state,
            status=result.status,
        )
        self._link_workflow_with_backbone(
            governance_call_id=governance_call_id,
            run_id=run_id,
            trigger_step="input_received",
            result_step={
                "allow": "policy_approved",
                "block": "policy_rejected",
                "require_approval": "require_approval",
            }.get(evaluation.disposition),
            projection=projection,
        )
        return GovernanceRuntimeDecision(
            evaluation=evaluation,
            workflow=workflow,
            projection=projection,
        )

    def resume_approval(
        self,
        approval_row: ApprovalRow,
        *,
        resolution: str,
        resolved_at: str | None,
    ) -> GovernanceRuntimeResume | None:
        run_id = approval_row.get("workflowRunId")
        suspended_node_id = approval_row.get("suspendedNodeId")
        suspended_token_id = approval_row.get("suspendedTokenId")
        workflow_id = approval_row.get("workflowId") or self.workflow_id
        conversation_id = approval_row.get("runtimeConversationId")
        turn_node_id = approval_row.get("runtimeTurnNodeId")
        governance_call_id = approval_row.get("governanceCallId")
        if not isinstance(run_id, str) or not run_id:
            return None
        if not isinstance(suspended_node_id, str) or not suspended_node_id:
            return None
        if not isinstance(suspended_token_id, str) or not suspended_token_id:
            return None
        if not isinstance(workflow_id, str) or not workflow_id:
            return None
        if not isinstance(conversation_id, str) or not conversation_id:
            return None
        if not isinstance(turn_node_id, str) or not turn_node_id:
            return None
        if not isinstance(governance_call_id, str) or not governance_call_id:
            return None

        next_step = "record_approval_granted"
        if resolution not in {"allow_once", "allow_always"}:
            next_step = "record_approval_denied"

        client_result = RunSuccess(
            conversation_node_id=None,
            state_update=[
                (
                    "u",
                    {
                        "approval_resolution": resolution,
                        "approval_resolved_at": resolved_at,
                        "approval_request_id": approval_row.get("approvalRequestId"),
                    },
                )
            ],
            _route_next=[next_step],
        )
        result = self.runtime.resume_run(
            run_id=run_id,
            suspended_node_id=suspended_node_id,
            suspended_token_id=suspended_token_id,
            client_result=client_result,
            workflow_id=workflow_id,
            conversation_id=conversation_id,
            turn_node_id=turn_node_id,
        )
        projection = cast(
            GovernanceProjectionRow,
            self._merge_projection(
            approval_row.get("runtimeProjection"),
            self._projection_from_state(result.final_state),
            ),
        )
        projection = cast(
            GovernanceProjectionRow,
            self._record_resolution_projection(
            projection=projection,
            workflow_id=workflow_id,
            run_id=run_id,
            governance_call_id=governance_call_id,
            resolution=resolution,
            resolved_at=resolved_at,
            ),
        )
        workflow = cast(
            WorkflowRunRow,
            self._workflow_snapshot(
            governance_call_id=governance_call_id,
            run_id=run_id,
            conversation_id=conversation_id,
            turn_node_id=turn_node_id,
            final_state=result.final_state,
            status=result.status,
            ),
        )
        workflow["approvalResolution"] = resolution
        workflow["projection"] = dict(projection)
        self._link_workflow_with_backbone(
            governance_call_id=governance_call_id,
            run_id=run_id,
            trigger_step="approval_received",
            result_step="governance_resolved",
            projection=projection,
        )
        return GovernanceRuntimeResume(
            workflow=workflow,
            projection=projection,
        )

    def record_completion(
        self,
        governance_call_id: str,
        *,
        completed_event: ToolCallCompletedEvent,
        workflow_run: WorkflowRunRow | None,
    ) -> GovernanceProjectionRow | None:
        if workflow_run is None:
            return None

        projection = cast(GovernanceProjectionRow, dict(workflow_run.get("projection") or {}))
        source_id = projection.get("resolutionNodeId") or projection.get("approvalNodeId") or projection.get("decisionNodeId") or projection.get("proposalNodeId")
        completion_node_id = f"gov|{workflow_run.get('runId', governance_call_id)}|completion|{completed_event.eventId}"
        outcome = completed_event.data.outcome
        self.conversation_engine.write.add_node(
            governance_node(
                node_id=completion_node_id,
                label=f"Completion {outcome}",
                summary=f"Tool call completed with {outcome}",
                doc_id=f"gov:{governance_call_id}",
                metadata={
                    "entity_type": "governance_completion",
                    "governance_call_id": governance_call_id,
                    "workflow_id": workflow_run.get("workflowId") or self.workflow_id,
                    "run_id": workflow_run.get("runId"),
                    "outcome": outcome,
                },
                properties={
                    "result_json": json.dumps(completed_event.data.result, default=str),
                    "error": completed_event.data.error,
                    "outcome": outcome,
                },
            )
        )
        if isinstance(source_id, str) and source_id:
            self.conversation_engine.write.add_edge(
                governance_edge(
                    edge_id=f"gov|{workflow_run.get('runId', governance_call_id)}|edge|completion|{completed_event.eventId}",
                    source_id=source_id,
                    target_id=completion_node_id,
                    relation="governance_completed_as",
                    label="governance_completed_as",
                    summary="Governance lineage completed with tool result",
                    doc_id=f"gov:{governance_call_id}",
                    metadata={"entity_type": "governance_edge"},
                )
            )
        projection["completionNodeId"] = completion_node_id
        projection["completionOutcome"] = outcome
        run_id = workflow_run.get("runId")
        if isinstance(run_id, str) and run_id:
            self._link_workflow_node_to_semantic_node(
                governance_call_id=governance_call_id,
                run_id=run_id,
                target_node_id=completion_node_id,
                relation="workflow_produced",
                summary="Workflow run produced completion result",
            )
            self._link_workflow_to_backbone_result(
                governance_call_id=governance_call_id,
                run_id=run_id,
                backbone_step="run_completed",
            )
        self._link_backbone_step_to_semantic_node(
            governance_call_id=governance_call_id,
            backbone_step="run_completed",
            target_node_id=completion_node_id,
            relation="governance_completed_at",
        )
        return projection

    @staticmethod
    def _projection_from_state(state: dict[str, Any]) -> GovernanceProjectionRow:
        projection = state.get("governance_projection")
        return cast(GovernanceProjectionRow, dict(projection) if isinstance(projection, dict) else {})

    @staticmethod
    def _merge_projection(*parts: Any) -> GovernanceProjectionRow:
        merged: dict[str, Any] = {}
        for part in parts:
            if isinstance(part, dict):
                merged.update(part)
        return cast(GovernanceProjectionRow, merged)

    def _record_resolution_projection(
        self,
        *,
        projection: GovernanceProjectionRow,
        workflow_id: str,
        run_id: str,
        governance_call_id: str | None,
        resolution: str,
        resolved_at: str | None,
    ) -> GovernanceProjectionRow:
        if not isinstance(governance_call_id, str) or not governance_call_id:
            return projection

        resolution_key = resolution or "unknown"
        resolution_node_id = str(
            projection.get("resolutionNodeId")
            or f"gov|{run_id}|resolution|{resolution_key}"
        )
        approval_node_id = projection.get("approvalNodeId")

        self.conversation_engine.write.add_node(
            governance_node(
                node_id=resolution_node_id,
                label=f"Approval {resolution_key}",
                summary=f"Approval resolved as {resolution_key}",
                doc_id=f"gov:{governance_call_id}",
                metadata={
                    "entity_type": "governance_approval_resolution",
                    "governance_call_id": governance_call_id,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "resolution": resolution_key,
                },
                properties={
                    "resolvedAt": resolved_at,
                    "resolution": resolution_key,
                },
            )
        )
        if isinstance(approval_node_id, str) and approval_node_id:
            self.conversation_engine.write.add_edge(
                governance_edge(
                    edge_id=f"gov|{run_id}|edge|approval->resolution|{resolution_key}",
                    source_id=approval_node_id,
                    target_id=resolution_node_id,
                    relation="governance_resolved_as",
                    label="governance_resolved_as",
                    summary="Approval resolved",
                    doc_id=f"gov:{governance_call_id}",
                    metadata={"entity_type": "governance_edge"},
                )
            )
        projection["resolutionNodeId"] = resolution_node_id
        return projection

    @staticmethod
    def _workflow_snapshot(
        *,
        governance_call_id: str | None,
        run_id: str,
        conversation_id: str,
        turn_node_id: str,
        final_state: dict[str, Any],
        status: str,
    ) -> WorkflowRunRow:
        suspended_node_id = None
        suspended_token_id = None
        rt_join = final_state.get("_rt_join")
        if isinstance(rt_join, dict):
            suspended = rt_join.get("suspended")
            if isinstance(suspended, list) and suspended:
                first = suspended[0]
                if isinstance(first, (list, tuple)) and len(first) >= 3:
                    suspended_node_id = str(first[0])
                    suspended_token_id = str(first[2])

        evaluation = final_state.get("policy_evaluation")
        decision = None
        if isinstance(evaluation, dict):
            decision = evaluation.get("disposition")

        return {
            "governanceCallId": governance_call_id,
            "workflowId": GOVERNANCE_WORKFLOW_ID,
            "runId": run_id,
            "conversationId": conversation_id,
            "turnNodeId": turn_node_id,
            "status": status,
            "decision": decision,
            "finalDisposition": final_state.get("final_disposition"),
            "approvalResolution": final_state.get("approval_resolution"),
            "suspendedNodeId": suspended_node_id,
            "suspendedTokenId": suspended_token_id,
            "projection": GovernanceRuntimeHost._projection_from_state(final_state),
        }

    def _link_workflow_with_backbone(
        self,
        *,
        governance_call_id: str,
        run_id: str,
        trigger_step: str | None,
        result_step: str | None,
        projection: GovernanceProjectionRow,
    ) -> None:
        if trigger_step:
            self._link_backbone_to_workflow(
                governance_call_id=governance_call_id,
                run_id=run_id,
                backbone_step=trigger_step,
            )
        if result_step:
            self._link_workflow_to_backbone_result(
                governance_call_id=governance_call_id,
                run_id=run_id,
                backbone_step=result_step,
            )
        for node_key in ("proposalNodeId", "decisionNodeId", "approvalNodeId", "resolutionNodeId"):
            node_id = projection.get(node_key)
            if isinstance(node_id, str) and node_id:
                self._link_workflow_node_to_semantic_node(
                    governance_call_id=governance_call_id,
                    run_id=run_id,
                    target_node_id=node_id,
                    relation="workflow_produced",
                    summary=f"Workflow run produced {node_key}",
                )
        self._anchor_projection_nodes_to_backbone(
            governance_call_id=governance_call_id,
            projection=projection,
            decision_step=result_step,
        )

    def _link_backbone_to_workflow(
        self,
        *,
        governance_call_id: str,
        run_id: str,
        backbone_step: str,
    ) -> None:
        self._ensure_backbone_step(governance_call_id, backbone_step)
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=f"govwf|{governance_call_id}|{backbone_step}|trigger|{run_id}",
                source_id=f"govbackbone|{governance_call_id}|{backbone_step}",
                target_id=f"wf_run|{run_id}",
                relation="governance_triggers_workflow",
                label="governance_triggers_workflow",
                summary=f"Backbone step {backbone_step} triggered workflow run",
                doc_id=f"gov:{governance_call_id}",
                metadata={"entity_type": "governance_edge"},
            )
        )

    def _link_workflow_to_backbone_result(
        self,
        *,
        governance_call_id: str,
        run_id: str,
        backbone_step: str,
    ) -> None:
        self._ensure_backbone_step(governance_call_id, backbone_step)
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=f"govwf|{governance_call_id}|result|{run_id}|{backbone_step}",
                source_id=f"wf_run|{run_id}",
                target_id=f"govbackbone|{governance_call_id}|{backbone_step}",
                relation="workflow_result_at",
                label="workflow_result_at",
                summary=f"Workflow run result anchored at backbone step {backbone_step}",
                doc_id=f"gov:{governance_call_id}",
                metadata={"entity_type": "governance_edge"},
            )
        )

    def _anchor_projection_nodes_to_backbone(
        self,
        *,
        governance_call_id: str,
        projection: GovernanceProjectionRow,
        decision_step: str | None,
    ) -> None:
        anchors = (
            ("proposalNodeId", "input_received", "governance_observed_at"),
            ("decisionNodeId", decision_step or "decision_recorded", "governance_decision_at"),
            ("approvalNodeId", "waiting_approval", "governance_approval_requested_at"),
            ("resolutionNodeId", "approval_received", "governance_approval_resolved_at"),
        )
        for node_key, backbone_step, relation in anchors:
            node_id = projection.get(node_key)
            if not isinstance(node_id, str) or not node_id:
                continue
            self._link_backbone_step_to_semantic_node(
                governance_call_id=governance_call_id,
                backbone_step=backbone_step,
                target_node_id=node_id,
                relation=relation,
            )

    def _link_backbone_step_to_semantic_node(
        self,
        *,
        governance_call_id: str,
        backbone_step: str,
        target_node_id: str,
        relation: str,
    ) -> None:
        self._ensure_backbone_step(governance_call_id, backbone_step)
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=f"govbackbone|{governance_call_id}|runtime|{backbone_step}|{target_node_id}|{relation}",
                source_id=f"govbackbone|{governance_call_id}|{backbone_step}",
                target_id=target_node_id,
                relation=relation,
                label=relation,
                summary=f"Backbone step {backbone_step} references runtime semantic node {target_node_id}",
                doc_id=f"gov:{governance_call_id}",
                metadata={
                    "entity_type": "governance_backbone_side_event",
                    "governance_call_id": governance_call_id,
                    "step": backbone_step,
                },
            )
        )

    def _link_workflow_node_to_semantic_node(
        self,
        *,
        governance_call_id: str,
        run_id: str,
        target_node_id: str,
        relation: str,
        summary: str,
    ) -> None:
        self.conversation_engine.write.add_edge(
            governance_edge(
                edge_id=f"govwf|{governance_call_id}|node|{run_id}|{target_node_id}|{relation}",
                source_id=f"wf_run|{run_id}",
                target_id=target_node_id,
                relation=relation,
                label=relation,
                summary=summary,
                doc_id=f"gov:{governance_call_id}",
                metadata={"entity_type": "governance_edge"},
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
                doc_id=f"gov:{governance_call_id}",
                metadata={
                    "entity_type": "governance_backbone_step",
                    "governance_call_id": governance_call_id,
                    "step": step,
                },
                properties={"governanceCallId": governance_call_id, "step": step},
            )
        )
        return node_id


_governance_runtime_host: GovernanceRuntimeHost | None = None


def get_governance_runtime_host() -> GovernanceRuntimeHost:
    global _governance_runtime_host
    if _governance_runtime_host is None:
        _governance_runtime_host = GovernanceRuntimeHost()
    return _governance_runtime_host


def reset_governance_runtime_host() -> None:
    global _governance_runtime_host
    _governance_runtime_host = None
