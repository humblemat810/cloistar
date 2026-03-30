from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .models import (
    AfterToolCallPayload,
    ApprovalResolutionPayload,
    BeforeToolCallPayload,
)
from .policy import decide
from .store import store

app = FastAPI(
    title="Kogwistar OpenClaw Bridge",
    version="0.1.0",
    description="Thin governance bridge between OpenClaw hooks and Kogwistar.",
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/state")
def debug_state() -> dict:
    return store.snapshot()


@app.post("/policy/before-tool-call")
def before_tool_call(payload: BeforeToolCallPayload) -> dict:
    store.append_event("tool_call_proposed", payload.model_dump())

    decision = decide(payload.toolName, payload.params)
    out = decision.model_dump()

    if out["decision"] == "block":
        store.append_event("tool_call_blocked", {"input": payload.model_dump(), "decision": out})
        return out

    if out["decision"] == "requireApproval":
        approval_id = store.create_approval({"input": payload.model_dump(), "decision": out})
        out["approvalId"] = approval_id
        store.append_event("tool_call_approval_requested", {"input": payload.model_dump(), "decision": out})
        return out

    store.append_event("tool_call_allowed", {"input": payload.model_dump(), "decision": out})
    return out


@app.post("/events/after-tool-call")
def after_tool_call(payload: AfterToolCallPayload) -> dict:
    store.append_event("tool_call_completed", payload.model_dump())
    return {"ok": True}


@app.post("/approval/resolution")
def approval_resolution(payload: ApprovalResolutionPayload) -> dict:
    if payload.approvalId:
        updated = store.resolve_approval(payload.approvalId, payload.resolution)
        if updated is None:
            raise HTTPException(status_code=404, detail="approval not found")

    store.append_event("tool_call_approval_resolved", payload.model_dump())
    return {"ok": True}
