from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .domain.governance_append import append_approval_resolution, append_event, register_approval_request
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


def _start_approval_listener() -> bool:
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global approval_listener_process
    try:
        yield
    finally:
        if approval_listener_process is not None and approval_listener_process.poll() is None:
            approval_listener_process.terminate()
            try:
                approval_listener_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                approval_listener_process.kill()
        approval_listener_process = None


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
    started = _start_approval_listener()
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
            store.attach_runtime_to_approval(
                approval_id,
                {
                    "workflowId": runtime_decision.workflow.get("workflowId"),
                    "workflowRunId": runtime_decision.workflow.get("runId"),
                    "runtimeConversationId": runtime_decision.workflow.get("conversationId"),
                    "runtimeTurnNodeId": runtime_decision.workflow.get("turnNodeId"),
                    "suspendedNodeId": runtime_decision.workflow.get("suspendedNodeId"),
                    "suspendedTokenId": runtime_decision.workflow.get("suspendedTokenId"),
                    "runtimeProjection": dict(runtime_decision.projection),
                },
            )

    return project_decision(evaluation, approval_id).model_dump()


@app.post("/events/after-tool-call")
def after_tool_call(payload: OpenClawAfterToolCallPayload) -> dict:
    receipt = build_receipt("after_tool_call", payload)
    store.record_receipt(receipt)
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
    updated = append_approval_resolution(store, resolved_event, follow_up_event)
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


@app.post("/gateway/plugin-approval/requested")
def gateway_plugin_approval_requested(payload: dict) -> dict:
    store.register_gateway_approval("plugin", payload)
    return {"ok": True}


@app.post("/gateway/plugin-approval/resolved")
def gateway_plugin_approval_resolved(payload: dict) -> dict:
    store.resolve_gateway_approval("plugin", payload)
    return {"ok": True}
