from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .domain.governance_append import append_approval_resolution, append_event, register_approval_request
from .domain.governance_models import ApprovalRuntimeAttachmentRow
from .integrations.openclaw_dto import (
    OpenClawAfterToolCallPayload,
    OpenClawApprovalResolutionPayload,
    OpenClawBeforeToolCallPayload,
)
from .integrations.openclaw_mapper import (
    approval_events_from_policy,
    build_receipt,
    canonicalize_after_tool_call,
    canonicalize_approval_resolution,
    canonicalize_before_tool_call,
    decision_event_from_policy,
    follow_up_event_for_resolution,
    result_and_completion_events_from_policy,
    result_and_completion_events_from_resolution,
)
from .policy import decide
from .projections.openclaw_projection import project_decision
from .runtime import get_governance_runtime_host
from .store import store


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _approval_listener_script() -> Path:
    return _repo_root() / "scripts" / "lib" / "openclaw-gateway-approval-listener.mjs"


approval_listener_process: subprocess.Popen[str] | None = None


def _stop_approval_listener() -> None:
    global approval_listener_process

    if approval_listener_process is None or approval_listener_process.poll() is not None:
        approval_listener_process = None
        return

    approval_listener_process.terminate()
    try:
        approval_listener_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        approval_listener_process.kill()
        approval_listener_process.wait(timeout=5)
    approval_listener_process = None


def _start_approval_listener(*, force_restart: bool = False) -> bool:
    global approval_listener_process

    should_start_listener = os.getenv("OPENCLAW_APPROVAL_EVENT_SUBSCRIPTION") == "1"
    listener_script = _approval_listener_script()
    node_bin = os.getenv("OPENCLAW_NODE_BIN") or "node"
    store.update_approval_subscription_status(
        {
            "enabled": should_start_listener,
        }
    )
    if not should_start_listener or not listener_script.exists():
        return False
    if force_restart:
        _stop_approval_listener()
    if approval_listener_process is not None and approval_listener_process.poll() is None:
        store.update_approval_subscription_status({"started": True})
        return True

    env = dict(os.environ)
    env.setdefault("BRIDGE_URL", "http://127.0.0.1:8788")
    approval_listener_process = subprocess.Popen(
        [node_bin, str(listener_script)],
        cwd=str(_repo_root()),
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
        text=True,
    )
    store.update_approval_subscription_status({"started": True})
    return True


def _is_approval_pending_after_tool_call(payload: OpenClawAfterToolCallPayload) -> bool:
    result = payload.result
    if not isinstance(result, dict):
        return False
    details = result.get("details")
    if not isinstance(details, dict):
        return False
    status = details.get("status")
    if not isinstance(status, str):
        return False
    normalized = status.strip().lower().replace("_", "-")
    return normalized == "approval-pending"


def _apply_approval_resolution_payload(
    payload: OpenClawApprovalResolutionPayload,
    *,
    approval: dict,
) -> dict:
    receipt = build_receipt("approval_resolution", payload)
    store.record_receipt(receipt)

    resolved_event = canonicalize_approval_resolution(
        payload,
        receipt,
        approval_request_id=payload.approvalId,
        governance_call_id=approval["governanceCallId"],
    )
    resolved_event.causationId = approval["requestedEventId"]
    follow_up_event = follow_up_event_for_resolution(resolved_event, approval["suspensionId"])
    result_event, completed_event = result_and_completion_events_from_resolution(
        resolved_event,
        follow_up_event,
    )
    updated = append_approval_resolution(
        store,
        resolved_event,
        follow_up_event,
        result_event=result_event,
        completed_event=completed_event,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="approval not found")

    runtime_resume = None
    try:
        runtime_resume = get_governance_runtime_host().resume_approval(
            approval,
            resolution=resolved_event.data.resolution,
            resolved_at=resolved_event.data.resolvedAt.isoformat(),
        )
    except Exception as exc:
        store.upsert_workflow_run(
            approval["governanceCallId"],
            {"resumeError": str(exc)},
        )

    if runtime_resume is not None:
        store.upsert_workflow_run(approval["governanceCallId"], runtime_resume.workflow)
        store.upsert_governance_projection(approval["governanceCallId"], runtime_resume.projection)

    return {"ok": True}


def _gateway_decision_to_resolution(decision: str | None) -> str | None:
    if not isinstance(decision, str):
        return None
    normalized = decision.strip().lower().replace("_", "-")
    mapping = {
        "allow-once": "allow-once",
        "allow-always": "allow-always",
        "deny": "deny",
        "timeout": "timeout",
        "cancelled": "cancelled",
    }
    return mapping.get(normalized)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        _stop_approval_listener()


app = FastAPI(
    title="Kogwistar OpenClaw Bridge",
    version="0.1.0",
    description="Thin governance bridge between OpenClaw hooks and Kogwistar.",
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/state")
def debug_state() -> dict:
    return store.snapshot()


@app.post("/gateway/approval-subscription/start")
def start_gateway_approval_subscription() -> dict[str, bool]:
    started = _start_approval_listener(force_restart=True)
    return {"ok": started}


@app.post("/gateway/approval-subscription/status")
def update_gateway_approval_subscription_status(payload: dict) -> dict:
    status = store.update_approval_subscription_status(payload)
    return {"ok": True, "status": status}


@app.post("/policy/before-tool-call")
def before_tool_call(payload: OpenClawBeforeToolCallPayload) -> dict:
    receipt = build_receipt("before_tool_call", payload)
    store.record_receipt(receipt)

    observed_event = canonicalize_before_tool_call(payload, receipt)
    append_event(store, observed_event)

    runtime_decision = None
    try:
        runtime_decision = get_governance_runtime_host().evaluate_proposal(
            observed_event,
            policy_evaluator=decide,
            store=store,
        )
        evaluation = runtime_decision.evaluation
        store.upsert_workflow_run(observed_event.subject.governanceCallId, runtime_decision.workflow)
        store.upsert_governance_projection(observed_event.subject.governanceCallId, runtime_decision.projection)
    except Exception as exc:
        evaluation = decide(observed_event.data.tool.name, observed_event.data.tool.params)
        store.upsert_workflow_run(
            observed_event.subject.governanceCallId,
            {
                "status": "runtime_fallback",
                "workflowId": None,
                "runId": None,
                "decision": evaluation.disposition,
                "runtimeError": str(exc),
            },
        )

    decision_event = decision_event_from_policy(observed_event, evaluation)
    append_event(store, decision_event)

    approval_id: str | None = None
    if evaluation.disposition == "require_approval" and evaluation.approval is not None:
        approval_event, suspended_event = approval_events_from_policy(decision_event, evaluation.approval)
        append_event(store, approval_event)
        append_event(store, suspended_event)
        register_approval_request(store, approval_event, suspended_event.data.suspensionId)
        approval_id = approval_event.data.approvalRequestId
        if runtime_decision is not None:
            runtime_attachment: ApprovalRuntimeAttachmentRow = {
                "workflowId": runtime_decision.workflow.get("workflowId"),
                "workflowRunId": runtime_decision.workflow.get("runId"),
                "runtimeConversationId": runtime_decision.workflow.get("conversationId"),
                "runtimeTurnNodeId": runtime_decision.workflow.get("turnNodeId"),
                "suspendedNodeId": runtime_decision.workflow.get("suspendedNodeId"),
                "suspendedTokenId": runtime_decision.workflow.get("suspendedTokenId"),
                "runtimeProjection": dict(runtime_decision.projection),
            }
            store.attach_runtime_to_approval(
                approval_id,
                runtime_attachment,
            )
    elif evaluation.disposition in {"allow", "block"}:
        result_event, completed_event = result_and_completion_events_from_policy(decision_event)
        append_event(store, result_event)
        append_event(store, completed_event)

    return project_decision(evaluation, approval_id).model_dump()


@app.post("/events/after-tool-call")
def after_tool_call(payload: OpenClawAfterToolCallPayload) -> dict:
    receipt = build_receipt("after_tool_call", payload)
    store.record_receipt(receipt)
    if _is_approval_pending_after_tool_call(payload):
        return {"ok": True, "status": "approval_pending"}
    completed_event = canonicalize_after_tool_call(payload, receipt)
    append_event(store, completed_event)
    workflow_run = store.get_workflow_run(completed_event.subject.governanceCallId)
    if workflow_run is not None:
        try:
            projection = get_governance_runtime_host().record_completion(
                completed_event.subject.governanceCallId,
                completed_event=completed_event,
                workflow_run=workflow_run,
            )
            if projection is not None:
                store.upsert_governance_projection(completed_event.subject.governanceCallId, projection)
                store.upsert_workflow_run(
                    completed_event.subject.governanceCallId,
                    {
                        "status": "completed",
                        "projection": projection,
                    },
                )
        except Exception as exc:
            store.upsert_workflow_run(
                completed_event.subject.governanceCallId,
                {"completionProjectionError": str(exc)},
            )
    return {"ok": True}


@app.post("/approval/resolution")
def approval_resolution(payload: OpenClawApprovalResolutionPayload) -> dict:
    if payload.approvalId is None:
        raise HTTPException(status_code=404, detail="approval not found")

    approval = store.get_approval(payload.approvalId)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return _apply_approval_resolution_payload(payload, approval=approval)


@app.post("/gateway/plugin-approval/requested")
def gateway_plugin_approval_requested(payload: dict) -> dict:
    return _gateway_approval_requested("plugin", payload)


@app.post("/gateway/exec-approval/requested")
def gateway_exec_approval_requested(payload: dict) -> dict:
    return _gateway_approval_requested("exec", payload)


@app.post("/gateway/plugin-approval/resolved")
def gateway_plugin_approval_resolved(payload: dict) -> dict:
    return _gateway_approval_resolved("plugin", payload)


@app.post("/gateway/exec-approval/resolved")
def gateway_exec_approval_resolved(payload: dict) -> dict:
    return _gateway_approval_resolved("exec", payload)


def _gateway_approval_requested(kind: str, payload: dict) -> dict:
    store.register_gateway_approval(kind, payload)
    return {"ok": True}


from .kg_models import (
    EdgeCreateIn,
    EdgeGetIn,
    EdgeUpdateIn,
    NodeCreateIn,
    NodeGetIn,
    NodeUpdateIn,
    QueryIn,
)
from kogwistar.engine_core.models import Node, Edge, Span, Grounding


def _gateway_approval_resolved(kind: str, payload: dict) -> dict:
    gateway_record = store.resolve_gateway_approval(kind, payload)
    if gateway_record is None:
        return {"ok": True}

    bridge_approval_id = gateway_record.get("bridgeApprovalId")
    resolution = _gateway_decision_to_resolution(payload.get("decision"))
    request = payload.get("request")
    request_data = request if isinstance(request, dict) else {}
    approval = None
    if isinstance(bridge_approval_id, str) and bridge_approval_id:
        approval = store.get_approval(bridge_approval_id)
    if approval is None:
        approval = store.find_approval_for_gateway_request(
            request_data if request_data else gateway_record.get("request") or {}
        )
        if approval is not None:
            bridge_approval_id = approval.get("approvalRequestId")
    if isinstance(bridge_approval_id, str) and bridge_approval_id and resolution is not None:
        approval = approval or store.get_approval(bridge_approval_id)
        if approval is not None and approval.get("status") == "pending":
            synthetic_payload = OpenClawApprovalResolutionPayload(
                pluginId="openclaw.gateway",
                sessionId=request_data.get("sessionKey") or approval.get("sessionId"),
                toolName=request_data.get("toolName") or approval.get("toolName"),
                resolution=resolution,
                approvalId=bridge_approval_id,
                rawEvent=dict(payload),
            )
            return _apply_approval_resolution_payload(synthetic_payload, approval=approval)
    return {"ok": True}


@app.post("/kg/node/create")
def kg_node_create(inp: NodeCreateIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    # Manual CRUD nodes need at least one mention grounding
    dummy_span = Span.from_dummy_for_conversation("manual_crud")
    node = Node(
        label=inp.label,
        type=inp.type if inp.type in ["entity", "relationship", "reference_pointer"] else "entity",
        summary=inp.summary or "",
        properties=inp.properties or {},
        metadata=inp.metadata or {},
        doc_id=inp.doc_id,
        mentions=[Grounding(spans=[dummy_span])]
    )
    eng.write.add_node(node)
    return {"ok": True, "id": node.id}


@app.post("/kg/node/get")
def kg_node_get(inp: NodeGetIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    nodes = eng.read.get_nodes(
        ids=inp.ids,
        where=inp.where,
        limit=inp.limit,
        resolve_mode=inp.resolve_mode,
    )
    return {"ok": True, "nodes": [n.model_dump(mode="json") for n in nodes]}


@app.post("/kg/node/delete")
def kg_node_delete(node_id: str) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    ok = eng.tombstone_node(node_id)
    return {"ok": ok}


@app.post("/kg/node/update")
def kg_node_update(inp: NodeUpdateIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    ok = eng.redirect_node(inp.from_id, inp.to_id)
    return {"ok": ok}


@app.post("/kg/edge/create")
def kg_edge_create(inp: EdgeCreateIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    # Manual CRUD edges need at least one mention grounding
    dummy_span = Span.from_dummy_for_conversation("manual_crud")
    edge = Edge(
        relation=inp.relation,
        source_ids=inp.source_ids,
        target_ids=inp.target_ids,
        type="relationship",
        label=inp.label or "",
        summary=inp.summary or "",
        properties=inp.properties or {},
        metadata=inp.metadata or {},
        doc_id=inp.doc_id,
        mentions=[Grounding(spans=[dummy_span])],
        source_edge_ids=[],
        target_edge_ids=[]
    )
    eng.write.add_edge(edge)
    return {"ok": True, "id": edge.id}


@app.post("/kg/edge/get")
def kg_edge_get(inp: EdgeGetIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    edges = eng.read.get_edges(
        ids=inp.ids,
        where=inp.where,
        limit=inp.limit,
        resolve_mode=inp.resolve_mode,
    )
    return {"ok": True, "edges": [e.model_dump(mode="json") for e in edges]}


@app.post("/kg/edge/delete")
def kg_edge_delete(edge_id: str) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    ok = eng.tombstone_edge(edge_id)
    return {"ok": ok}


@app.post("/kg/edge/update")
def kg_edge_update(inp: EdgeUpdateIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    ok = eng.redirect_edge(inp.from_id, inp.to_id)
    return {"ok": ok}


@app.post("/kg/query")
def kg_query(inp: QueryIn) -> dict:
    eng = get_governance_runtime_host().conversation_engine
    nodes_batches = eng.read.query_nodes(
        query=inp.query,
        query_embeddings=inp.query_embeddings,
        where=inp.where,
        n_results=inp.n_results,
    )
    # Flatten batches (one batch per query embedding)
    nodes = [n for batch in nodes_batches for n in batch]
    return {"ok": True, "nodes": [n.model_dump(mode="json") for n in nodes]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8799)
