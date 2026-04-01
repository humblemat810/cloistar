from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OpenClawDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenClawBeforeToolCallPayload(OpenClawDto):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    params: Any = None
    rawEvent: dict[str, Any] = Field(default_factory=dict)


class OpenClawAfterToolCallPayload(OpenClawDto):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    params: Any = None
    result: Any = None
    error: str | None = None
    durationMs: int | None = None
    rawEvent: dict[str, Any] = Field(default_factory=dict)


class OpenClawApprovalResolutionPayload(OpenClawDto):
    pluginId: str
    sessionId: str | None = None
    toolName: str | None = None
    resolution: Literal["allow-once", "allow-always", "deny", "timeout", "cancelled"]
    approvalId: str | None = None
    rawEvent: dict[str, Any] = Field(default_factory=dict)


class OpenClawAllowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow"] = "allow"
    annotations: dict[str, Any] | None = None


class OpenClawBlockDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["block"] = "block"
    reason: str


class OpenClawRequireApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["requireApproval"] = "requireApproval"
    title: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"
    timeoutMs: int = Field(default=120_000, ge=1)
    timeoutBehavior: Literal["allow", "deny"] = "deny"
    approvalId: str | None = None


OpenClawDecision = OpenClawAllowDecision | OpenClawBlockDecision | OpenClawRequireApprovalDecision
