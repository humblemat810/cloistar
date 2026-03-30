from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class BeforeToolCallPayload(BaseModel):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    params: Any = None
    rawEvent: Any = None


class AfterToolCallPayload(BaseModel):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    params: Any = None
    result: Any = None
    rawEvent: Any = None


class ApprovalResolutionPayload(BaseModel):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    resolution: str
    approvalId: str | None = None
    rawEvent: Any = None


class AllowDecision(BaseModel):
    decision: Literal["allow"] = "allow"
    annotations: dict[str, Any] | None = None


class BlockDecision(BaseModel):
    decision: Literal["block"] = "block"
    reason: str


class RequireApprovalDecision(BaseModel):
    decision: Literal["requireApproval"] = "requireApproval"
    title: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"
    timeoutMs: int = Field(default=120_000, ge=1)
    timeoutBehavior: Literal["allow", "deny"] = "deny"
    approvalId: str | None = None
