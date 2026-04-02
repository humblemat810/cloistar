from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from kogwistar.engine_core.engine import GraphKnowledgeEngine
from kogwistar.runtime.models import RunSuccess
from kogwistar.runtime.runtime import WorkflowRuntime

from ..domain.governance_models import PolicyEvaluation, ToolCallCompletedEvent, ToolCallObservedEvent
from .governance_design import GOVERNANCE_WORKFLOW_ID, ensure_governance_workflow_design
from .governance_graph import governance_edge, governance_node
from .governance_resolvers import governance_resolver


def _zero_embeddings(texts: list[str]) -> list[list[float]]:
    return [[0.0, 0.0, 0.0] for _ in texts]


@dataclass
class GovernanceRuntimeDecision:
    evaluation: PolicyEvaluation
    workflow: dict[str, Any]
    projection: dict[str, Any]


@dataclass
class GovernanceRuntimeResume:
    workflow: dict[str, Any]
    projection: dict[str, Any]


class GovernanceRuntimeHost:
    def __init__(self, *, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or self._default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_id = GOVERNANCE_WORKFLOW_ID
        self.workflow_engine = GraphKnowledgeEngine(
            persist_directory=str(self.data_dir / "workflow"),
            kg_graph_type="workflow",
            embedding_function=_zero_embeddings,
        )
        self.conversation_engine = GraphKnowledgeEngine(
            persist_directory=str(self.data_dir / "conversation"),
            kg_graph_type="conversation",
            embedding_function=_zero_embeddings,
        )
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
        return GovernanceRuntimeDecision(
            evaluation=evaluation,
            workflow=workflow,
            projection=projection,
        )

    def resume_approval(
        self,
        approval_row: dict[str, Any],
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
        if not all(
            isinstance(value, str) and value
            for value in (run_id, suspended_node_id, suspended_token_id, workflow_id, conversation_id, turn_node_id)
        ):
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
        projection = self._projection_from_state(result.final_state)
        projection = self._record_resolution_projection(
            projection=projection,
            workflow_id=workflow_id,
            run_id=run_id,
            governance_call_id=governance_call_id,
            resolution=resolution,
            resolved_at=resolved_at,
        )
        workflow = self._workflow_snapshot(
            governance_call_id=governance_call_id,
            run_id=run_id,
            conversation_id=conversation_id,
            turn_node_id=turn_node_id,
            final_state=result.final_state,
            status=result.status,
        )
        workflow["approvalResolution"] = resolution
        workflow["projection"] = dict(projection)
        return GovernanceRuntimeResume(
            workflow=workflow,
            projection=projection,
        )

    def record_completion(
        self,
        governance_call_id: str,
        *,
        completed_event: ToolCallCompletedEvent,
        workflow_run: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if workflow_run is None:
            return None

        projection = dict(workflow_run.get("projection") or {})
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
        return projection

    @staticmethod
    def _projection_from_state(state: dict[str, Any]) -> dict[str, Any]:
        projection = state.get("governance_projection")
        return dict(projection) if isinstance(projection, dict) else {}

    def _record_resolution_projection(
        self,
        *,
        projection: dict[str, Any],
        workflow_id: str,
        run_id: str,
        governance_call_id: str | None,
        resolution: str,
        resolved_at: str | None,
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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


_governance_runtime_host: GovernanceRuntimeHost | None = None


def get_governance_runtime_host() -> GovernanceRuntimeHost:
    global _governance_runtime_host
    if _governance_runtime_host is None:
        _governance_runtime_host = GovernanceRuntimeHost()
    return _governance_runtime_host


def reset_governance_runtime_host() -> None:
    global _governance_runtime_host
    _governance_runtime_host = None
