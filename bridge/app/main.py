from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Body, Query

from .domain.governance_append import append_event, register_approval_request
from .domain.governance_models import ApprovalRequestSpec, ApprovalRuntimeAttachmentRow
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


def _approval_debug_enabled() -> bool:
    value = os.getenv("BRIDGE_APPROVAL_DEBUG", "1").strip().lower()
    return value not in {"0", "false", "off", "no"}


def _approval_debug(message: str, **fields: object) -> None:
    if not _approval_debug_enabled():
        return
    detail = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields))
    print(f"[bridge-approval-debug] {message}" + (f" {detail}" if detail else ""), file=sys.stderr, flush=True)


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
    _approval_debug(
        "apply_resolution:start",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        sessionId=payload.sessionId,
        toolName=payload.toolName,
        resolution=payload.resolution,
        approvalStatus=approval.get("status"),
        suspensionId=approval.get("suspensionId"),
    )
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
    updated = store.resolve_approval(
        resolved_event.data.approvalRequestId,
        resolved_event.data.resolution,
        resolved_event.data.resolvedAt.isoformat(),
    )
    if updated is None:
        _approval_debug(
            "apply_resolution:resolve_failed",
            approvalId=payload.approvalId,
            governanceCallId=approval.get("governanceCallId"),
        )
        raise HTTPException(status_code=404, detail="approval not found")
    _approval_debug(
        "apply_resolution:resolve_ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        updatedStatus=updated.get("status") if isinstance(updated, dict) else None,
    )
    _approval_debug(
        "apply_resolution:append_event:start",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=resolved_event.eventType,
    )
    append_event(store, resolved_event)
    _approval_debug(
        "apply_resolution:append_event:ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=resolved_event.eventType,
    )
    _approval_debug(
        "apply_resolution:append_event:start",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=follow_up_event.eventType,
    )
    append_event(store, follow_up_event)
    _approval_debug(
        "apply_resolution:append_event:ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=follow_up_event.eventType,
    )
    _approval_debug(
        "apply_resolution:append_event:start",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=result_event.eventType,
    )
    append_event(store, result_event)
    _approval_debug(
        "apply_resolution:append_event:ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=result_event.eventType,
    )
    _approval_debug(
        "apply_resolution:append_event:start",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=completed_event.eventType,
    )
    append_event(store, completed_event)
    _approval_debug(
        "apply_resolution:append_event:ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        eventType=completed_event.eventType,
    )
    _approval_debug(
        "apply_resolution:append_ok",
        approvalId=payload.approvalId,
        governanceCallId=approval.get("governanceCallId"),
        updatedStatus=updated.get("status") if isinstance(updated, dict) else None,
    )

    runtime_resume = None
    try:
        runtime_resume = get_governance_runtime_host().resume_approval(
            approval,
            resolution=resolved_event.data.resolution,
            resolved_at=resolved_event.data.resolvedAt.isoformat(),
        )
    except Exception as exc:
        _approval_debug(
            "apply_resolution:runtime_resume_error",
            approvalId=payload.approvalId,
            governanceCallId=approval.get("governanceCallId"),
            error=str(exc),
        )
        store.upsert_workflow_run(
            approval["governanceCallId"],
            {"resumeError": str(exc)},
        )

    if runtime_resume is not None:
        _approval_debug(
            "apply_resolution:runtime_resume_ok",
            approvalId=payload.approvalId,
            governanceCallId=approval.get("governanceCallId"),
            workflowStatus=runtime_resume.workflow.get("status"),
            workflowFinalDisposition=runtime_resume.workflow.get("finalDisposition"),
        )
        store.upsert_workflow_run(approval["governanceCallId"], runtime_resume.workflow)
        store.upsert_governance_projection(approval["governanceCallId"], runtime_resume.projection)
    else:
        _approval_debug(
            "apply_resolution:runtime_resume_none",
            approvalId=payload.approvalId,
            governanceCallId=approval.get("governanceCallId"),
        )

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

    if evaluation.disposition == "require_approval" and evaluation.approval is None:
        fallback_eval = decide(observed_event.data.tool.name, observed_event.data.tool.params)
        fallback_spec = fallback_eval.approval if fallback_eval.disposition == "require_approval" else None
        ensured_spec = fallback_spec or ApprovalRequestSpec(
            title=f"Approval required for {observed_event.data.tool.name or 'tool'}",
            description="Bridge backfilled approval because runtime evaluation omitted approval details.",
            severity="warning",
            timeoutMs=600_000,
            timeoutBehavior="deny",
            approvalScope="once",
        )
        _approval_debug(
            "before_tool_call:backfilled_missing_approval_spec",
            governanceCallId=observed_event.subject.governanceCallId,
            toolName=observed_event.data.tool.name,
            source="policy_fallback" if fallback_spec is not None else "bridge_default",
            decision=evaluation.disposition,
        )
        evaluation = evaluation.model_copy(update={"approval": ensured_spec})

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
        # Race guard: gateway approval may already be resolved before the bridge
        # creates the canonical approval row. If so, reconcile immediately.
        approval_row = store.get_approval(approval_id)
        if isinstance(approval_row, dict) and approval_row.get("status") == "pending":
            gateway_approval_id = approval_row.get("gatewayApprovalId")
            if isinstance(gateway_approval_id, str) and gateway_approval_id:
                gateway_row = store.get_gateway_approval(gateway_approval_id)
                if isinstance(gateway_row, dict):
                    gateway_decision = gateway_row.get("decision") or gateway_row.get("status")
                    deferred_resolution = _gateway_decision_to_resolution(
                        gateway_decision if isinstance(gateway_decision, str) else None
                    )
                    if deferred_resolution is not None and gateway_row.get("status") != "pending":
                        _approval_debug(
                            "before_tool_call:reconcile_deferred_gateway_resolution",
                            approvalId=approval_id,
                            gatewayApprovalId=gateway_approval_id,
                            gatewayStatus=gateway_row.get("status"),
                            gatewayDecision=gateway_row.get("decision"),
                            deferredResolution=deferred_resolution,
                        )
                        request = gateway_row.get("request")
                        request_data = request if isinstance(request, dict) else {}
                        synthetic_payload = OpenClawApprovalResolutionPayload(
                            pluginId="openclaw.gateway.deferred",
                            sessionId=request_data.get("sessionKey") or approval_row.get("sessionId"),
                            toolName=request_data.get("toolName") or approval_row.get("toolName"),
                            resolution=deferred_resolution,
                            approvalId=approval_id,
                            rawEvent={
                                "deferredGatewayApprovalId": gateway_approval_id,
                                "gatewayRecord": dict(gateway_row),
                            },
                        )
                        _apply_approval_resolution_payload(synthetic_payload, approval=approval_row)
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
    _approval_debug(
        "gateway_resolved:start",
        kind=kind,
        gatewayApprovalId=payload.get("id"),
        decision=payload.get("decision"),
        request=payload.get("request"),
    )
    gateway_record = store.resolve_gateway_approval(kind, payload)
    if gateway_record is None:
        _approval_debug(
            "gateway_resolved:no_gateway_record",
            kind=kind,
            gatewayApprovalId=payload.get("id"),
        )
        return {"ok": True}

    _approval_debug(
        "gateway_resolved:gateway_record",
        kind=kind,
        gatewayApprovalId=gateway_record.get("gatewayApprovalId"),
        bridgeApprovalId=gateway_record.get("bridgeApprovalId"),
        gatewayStatus=gateway_record.get("status"),
        request=gateway_record.get("request"),
    )
    bridge_approval_id = gateway_record.get("bridgeApprovalId")
    resolution = _gateway_decision_to_resolution(payload.get("decision"))
    request = payload.get("request")
    request_data = request if isinstance(request, dict) else {}
    approval = None
    if isinstance(bridge_approval_id, str) and bridge_approval_id:
        approval = store.get_approval(bridge_approval_id)
        _approval_debug(
            "gateway_resolved:lookup_by_bridge_id",
            bridgeApprovalId=bridge_approval_id,
            found=approval is not None,
        )
    if approval is None:
        approval = store.find_approval_for_gateway_request(
            request_data if request_data else gateway_record.get("request") or {}
        )
        _approval_debug(
            "gateway_resolved:lookup_by_request",
            request=request_data if request_data else gateway_record.get("request"),
            found=approval is not None,
        )
        if approval is not None:
            bridge_approval_id = approval.get("approvalRequestId")
    if approval is None:
        gateway_approval_id = gateway_record.get("gatewayApprovalId")
        if isinstance(gateway_approval_id, str) and gateway_approval_id:
            approval = store.find_approval_for_gateway_approval_id(gateway_approval_id)
            _approval_debug(
                "gateway_resolved:lookup_by_gateway_id",
                gatewayApprovalId=gateway_approval_id,
                found=approval is not None,
            )
            if approval is not None:
                bridge_approval_id = approval.get("approvalRequestId")
    if approval is None:
        session_key = request_data.get("sessionKey")
        if isinstance(session_key, str) and session_key:
            approval = store.find_pending_approval_for_session(session_key)
            _approval_debug(
                "gateway_resolved:lookup_by_session",
                sessionKey=session_key,
                found=approval is not None,
            )
            if approval is not None:
                bridge_approval_id = approval.get("approvalRequestId")
    if isinstance(bridge_approval_id, str) and bridge_approval_id and resolution is not None:
        approval = approval or store.get_approval(bridge_approval_id)
        _approval_debug(
            "gateway_resolved:pre_apply",
            bridgeApprovalId=bridge_approval_id,
            resolution=resolution,
            hasApproval=approval is not None,
            approvalStatus=approval.get("status") if isinstance(approval, dict) else None,
        )
        if approval is not None and approval.get("status") == "pending":
            synthetic_payload = OpenClawApprovalResolutionPayload(
                pluginId="openclaw.gateway",
                sessionId=request_data.get("sessionKey") or approval.get("sessionId"),
                toolName=request_data.get("toolName") or approval.get("toolName"),
                resolution=resolution,
                approvalId=bridge_approval_id,
                rawEvent=dict(payload),
            )
            _approval_debug(
                "gateway_resolved:applying_resolution",
                bridgeApprovalId=bridge_approval_id,
                sessionId=synthetic_payload.sessionId,
                toolName=synthetic_payload.toolName,
                resolution=synthetic_payload.resolution,
            )
            return _apply_approval_resolution_payload(synthetic_payload, approval=approval)
    _approval_debug(
        "gateway_resolved:no_apply",
        kind=kind,
        bridgeApprovalId=bridge_approval_id,
        resolution=resolution,
        hasApproval=approval is not None,
        approvalStatus=approval.get("status") if isinstance(approval, dict) else None,
    )
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
    return {"ok": True, "nodes": [n.model_dump(field_mode="backend") for n in nodes]}


@app.post("/kg/node/delete")
def kg_node_delete(
    node_id_body: str | None = Body(default=None, embed=True, alias="node_id"),
    node_id_query: str | None = Query(default=None, alias="node_id"),
) -> dict:
    node_id = node_id_body or node_id_query
    if not node_id:
        raise HTTPException(status_code=422, detail="node_id is required")
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
    return {"ok": True, "edges": [e.model_dump(field_mode="backend") for e in edges]}


@app.post("/kg/edge/delete")
def kg_edge_delete(
    edge_id_body: str | None = Body(default=None, embed=True, alias="edge_id"),
    edge_id_query: str | None = Query(default=None, alias="edge_id"),
) -> dict:
    edge_id = edge_id_body or edge_id_query
    if not edge_id:
        raise HTTPException(status_code=422, detail="edge_id is required")
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
    return {"ok": True, "nodes": [n.model_dump(field_mode="backend") for n in nodes]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8799)
