from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from kogwistar.runtime.models import RunSuccess, RunSuspended
from kogwistar.runtime.resolvers import MappingStepResolver

from .governance_graph import governance_edge, governance_node


governance_resolver = MappingStepResolver()
governance_resolver.set_state_schema(
    {
        "governance_projection": "u",
        "policy_evaluation": "u",
        "decision": "u",
        "risk_summary": "u",
        "prior_context": "u",
        "approval_spec": "u",
        "final_disposition": "u",
        "approval_resolution": "u",
        "approval_resolved_at": "u",
        "run_status": "u",
    }
)


def _deps(ctx) -> dict[str, Any]:
    deps = ctx.state_view.get("_deps")
    if not isinstance(deps, dict):
        raise RuntimeError("governance runtime requires dict _deps")
    return deps


def _projection(ctx) -> dict[str, Any]:
    current = ctx.state_view.get("governance_projection")
    return dict(current) if isinstance(current, dict) else {}


def _doc_id(ctx) -> str:
    governance_call_id = str(ctx.state_view["governance_call_id"])
    return f"gov:{governance_call_id}"


def _tool_name(ctx) -> str:
    proposal = ctx.state_view.get("proposal")
    if isinstance(proposal, dict):
        data = proposal.get("data")
        if isinstance(data, dict):
            tool = data.get("tool")
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                return tool["name"]
    return str(ctx.state_view.get("tool_name") or "")


def _tool_params(ctx) -> Any:
    proposal = ctx.state_view.get("proposal")
    if isinstance(proposal, dict):
        data = proposal.get("data")
        if isinstance(data, dict):
            tool = data.get("tool")
            if isinstance(tool, dict):
                return deepcopy(tool.get("params"))
    return deepcopy(ctx.state_view.get("tool_params"))


def _conversation_engine(ctx):
    deps = _deps(ctx)
    engine = deps.get("conversation_engine")
    if engine is None:
        raise RuntimeError("conversation_engine missing in governance deps")
    return engine


def _conversation_engine_or_none(ctx):
    deps = ctx.state_view.get("_deps")
    if not isinstance(deps, dict):
        return None
    return deps.get("conversation_engine")


def _append_node(
    ctx,
    *,
    node_id: str,
    entity_type: str,
    label: str,
    summary: str,
    metadata: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> str:
    engine = _conversation_engine(ctx)
    engine.write.add_node(
        governance_node(
            node_id=node_id,
            label=label,
            summary=summary,
            doc_id=_doc_id(ctx),
            metadata=metadata,
            properties=properties,
        )
    )
    return node_id


def _append_edge(
    ctx,
    *,
    edge_id: str,
    source_id: str,
    target_id: str,
    relation: str,
    label: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    engine = _conversation_engine(ctx)
    engine.write.add_edge(
        governance_edge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            label=label,
            summary=summary,
            doc_id=_doc_id(ctx),
            metadata=metadata,
        )
    )
    return edge_id


@governance_resolver.register("ingest_proposal")
def ingest_proposal(ctx):
    governance_call_id = str(ctx.state_view["governance_call_id"])
    proposal = deepcopy(ctx.state_view.get("proposal"))
    proposal_node_id = f"gov|{ctx.run_id}|proposal"
    _append_node(
        ctx,
        node_id=proposal_node_id,
        entity_type="governance_proposal",
        label=f"Proposal {governance_call_id}",
        summary=f"Observed {_tool_name(ctx)} proposal",
        metadata={
            "entity_type": "governance_proposal",
            "governance_call_id": governance_call_id,
            "workflow_id": ctx.workflow_id,
            "run_id": ctx.run_id,
            "tool_name": _tool_name(ctx),
        },
        properties={"payload_json": json.dumps(proposal, default=str)},
    )
    projection = _projection(ctx)
    projection["proposalNodeId"] = proposal_node_id
    return RunSuccess(
        conversation_node_id=proposal_node_id,
        state_update=[
            ("u", {"governance_projection": projection}),
            ("u", {"run_status": "observed"}),
        ],
    )


@governance_resolver.register("load_prior_context")
def load_prior_context(ctx):
    deps = _deps(ctx)
    store = deps.get("store")
    matching_count = 0
    if store is not None:
        if hasattr(store, "count_matching_approvals"):
            matching_count = int(store.count_matching_approvals(_tool_name(ctx)))
        else:
            snapshot = store.snapshot()
            matching_count = sum(
                1
                for approval in snapshot.get("approvals", {}).values()
                if approval.get("toolName") == _tool_name(ctx)
            )
    return RunSuccess(
        conversation_node_id=None,
        state_update=[
            ("u", {"prior_context": {"matchingApprovalCount": matching_count}}),
            ("u", {"run_status": "context_loaded"}),
        ],
    )


@governance_resolver.register("classify_risk")
def classify_risk(ctx):
    tool_name = _tool_name(ctx)
    params_blob = str(_tool_params(ctx) or "").lower()
    risk_level = "low"
    if tool_name in {"exec", "apply_patch"}:
        risk_level = "dangerous"
    elif any(marker in params_blob for marker in ("delete", "drop", "truncate", "chmod 777")):
        risk_level = "approval_candidate"
    elif any(marker in params_blob for marker in ("rm -rf", "shutdown", "reboot")):
        risk_level = "critical"
    return RunSuccess(
        conversation_node_id=None,
        state_update=[
            ("u", {"risk_summary": {"level": risk_level, "toolName": tool_name}}),
            ("u", {"run_status": "risk_classified"}),
        ],
    )


@governance_resolver.register("decide_governance")
def decide_governance(ctx):
    deps = _deps(ctx)
    policy_evaluator = deps.get("policy_evaluator")
    if policy_evaluator is None:
        raise RuntimeError("policy_evaluator missing in governance deps")

    evaluation = policy_evaluator(_tool_name(ctx), _tool_params(ctx))
    decision_node_id = f"gov|{ctx.run_id}|decision"
    _append_node(
        ctx,
        node_id=decision_node_id,
        entity_type="governance_decision",
        label=f"Decision {evaluation.disposition}",
        summary=f"Governance decision for {_tool_name(ctx)}",
        metadata={
            "entity_type": "governance_decision",
            "governance_call_id": str(ctx.state_view["governance_call_id"]),
            "workflow_id": ctx.workflow_id,
            "run_id": ctx.run_id,
            "decision": evaluation.disposition,
        },
        properties={"evaluation_json": json.dumps(evaluation.model_dump(mode="json"), default=str)},
    )

    projection = _projection(ctx)
    proposal_node_id = projection.get("proposalNodeId")
    if isinstance(proposal_node_id, str) and proposal_node_id:
        _append_edge(
            ctx,
            edge_id=f"gov|{ctx.run_id}|edge|proposal->decision",
            source_id=proposal_node_id,
            target_id=decision_node_id,
            relation="governance_decided",
            label="governance_decided",
            summary="Proposal received a governance decision",
            metadata={"entity_type": "governance_edge"},
        )

    projection["decisionNodeId"] = decision_node_id
    updates = [
        ("u", {"policy_evaluation": evaluation.model_dump(mode="json")}),
        ("u", {"decision": evaluation.disposition}),
        ("u", {"governance_projection": projection}),
        ("u", {"run_status": "decision_recorded"}),
    ]
    if evaluation.approval is not None:
        updates.append(("u", {"approval_spec": evaluation.approval.model_dump(mode="json")}))

    next_step = {
        "allow": "record_allow",
        "block": "record_block",
        "require_approval": "request_approval",
    }[evaluation.disposition]
    return RunSuccess(
        conversation_node_id=decision_node_id,
        state_update=updates,
        _route_next=[next_step],
    )


@governance_resolver.register("record_allow")
def record_allow(ctx):
    return RunSuccess(
        conversation_node_id=None,
        state_update=[
            ("u", {"final_disposition": "allow"}),
            ("u", {"run_status": "allow_recorded"}),
        ],
        _route_next=["close_run"],
    )


@governance_resolver.register("record_block")
def record_block(ctx):
    evaluation = ctx.state_view.get("policy_evaluation")
    reason = None
    if isinstance(evaluation, dict):
        reasons = evaluation.get("reasons")
        if isinstance(reasons, list) and reasons and isinstance(reasons[0], dict):
            reason = reasons[0].get("message")
    return RunSuccess(
        conversation_node_id=None,
        state_update=[
            ("u", {"final_disposition": "block"}),
            ("u", {"block_reason": reason}),
            ("u", {"run_status": "block_recorded"}),
        ],
        _route_next=["close_run"],
    )


@governance_resolver.register("request_approval")
def request_approval(ctx):
    projection = _projection(ctx)
    decision_node_id = projection.get("decisionNodeId")
    approval_spec = deepcopy(ctx.state_view.get("approval_spec"))
    approval_node_id = f"gov|{ctx.run_id}|approval"
    _append_node(
        ctx,
        node_id=approval_node_id,
        entity_type="governance_approval_request",
        label="Approval Requested",
        summary=f"Approval requested for {_tool_name(ctx)}",
        metadata={
            "entity_type": "governance_approval_request",
            "governance_call_id": str(ctx.state_view["governance_call_id"]),
            "workflow_id": ctx.workflow_id,
            "run_id": ctx.run_id,
        },
        properties={"approval_spec_json": json.dumps(approval_spec, default=str)},
    )
    if isinstance(decision_node_id, str) and decision_node_id:
        _append_edge(
            ctx,
            edge_id=f"gov|{ctx.run_id}|edge|decision->approval",
            source_id=decision_node_id,
            target_id=approval_node_id,
            relation="governance_requires_approval",
            label="governance_requires_approval",
            summary="Decision requires approval",
            metadata={"entity_type": "governance_edge"},
        )

    projection["approvalNodeId"] = approval_node_id
    return RunSuspended(
        conversation_node_id=approval_node_id,
        state_update=[
            ("u", {"governance_projection": projection}),
            ("u", {"run_status": "approval_pending"}),
        ],
        resume_payload={
            "type": "governance_approval",
            "governanceCallId": str(ctx.state_view["governance_call_id"]),
            "toolName": _tool_name(ctx),
            "approvalSpec": approval_spec,
        },
    )


def _record_approval_resolution(ctx, *, allowed: bool):
    projection = _projection(ctx)
    approval_node_id = projection.get("approvalNodeId")
    resolution = str(ctx.state_view.get("approval_resolution") or "")
    resolution_node_id = f"gov|{ctx.run_id}|resolution|{resolution or 'unknown'}"
    engine = _conversation_engine_or_none(ctx)
    conversation_node_id = None
    if engine is not None:
        _append_node(
            ctx,
            node_id=resolution_node_id,
            entity_type="governance_approval_resolution",
            label=f"Approval {resolution or 'resolved'}",
            summary=f"Approval resolved as {resolution or 'unknown'}",
            metadata={
                "entity_type": "governance_approval_resolution",
                "governance_call_id": str(ctx.state_view["governance_call_id"]),
                "workflow_id": ctx.workflow_id,
                "run_id": ctx.run_id,
                "resolution": resolution,
            },
            properties={"resolvedAt": ctx.state_view.get("approval_resolved_at")},
        )
        if isinstance(approval_node_id, str) and approval_node_id:
            _append_edge(
                ctx,
                edge_id=f"gov|{ctx.run_id}|edge|approval->resolution|{resolution or 'unknown'}",
                source_id=approval_node_id,
                target_id=resolution_node_id,
                relation="governance_resolved_as",
                label="governance_resolved_as",
                summary="Approval resolved",
                metadata={"entity_type": "governance_edge"},
            )
        conversation_node_id = resolution_node_id

    projection["resolutionNodeId"] = resolution_node_id
    final_disposition = "allow" if allowed else "block"
    return RunSuccess(
        conversation_node_id=conversation_node_id,
        state_update=[
            ("u", {"governance_projection": projection}),
            ("u", {"final_disposition": final_disposition}),
            ("u", {"run_status": "approval_resolved"}),
        ],
        _route_next=["close_run"],
    )


@governance_resolver.register("record_approval_granted")
def record_approval_granted(ctx):
    return _record_approval_resolution(ctx, allowed=True)


@governance_resolver.register("record_approval_denied")
def record_approval_denied(ctx):
    return _record_approval_resolution(ctx, allowed=False)


@governance_resolver.register("close_run")
def close_run(ctx):
    return RunSuccess(
        conversation_node_id=None,
        state_update=[("u", {"run_status": "closed"})],
    )
