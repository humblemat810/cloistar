from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Literal, NotRequired, TypedDict, TypeAlias
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


def stable_governance_call_id(parts: list[str | None]) -> str:
    seed = "|".join(part or "" for part in parts)
    return str(uuid5(NAMESPACE_URL, f"kogwistar:openclaw:{seed}"))


def payload_digest(payload: Any) -> str:
    normalized = _normalize(payload)
    return sha256(normalized.encode("utf-8")).hexdigest()


def _normalize(payload: Any) -> str:
    if isinstance(payload, BaseModel):
        return payload.model_dump_json(by_alias=True, exclude_none=False)

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntegrationReceipt(CanonicalModel):
    receiptId: str = Field(default_factory=new_id)
    receivedAt: datetime = Field(default_factory=utc_now)
    sourceSystem: Literal["openclaw"] = "openclaw"
    sourceEventType: str
    adapterVersion: str = "v1"
    payloadSha256: str
    payload: dict[str, Any]
    parseStatus: Literal["accepted", "rejected"] = "accepted"
    notes: list[str] = Field(default_factory=list)


class ProducerRef(CanonicalModel):
    system: str = "kogwistar-openclaw-adapter"
    component: str = "bridge"
    adapterVersion: str = "v1"


class GovernanceSubject(CanonicalModel):
    governanceCallId: str
    approvalRequestId: str | None = None


class ProvenanceRef(CanonicalModel):
    sourceSystem: Literal["openclaw"] = "openclaw"
    sourceEventType: str
    receiptId: str
    payloadSha256: str
    sourceSchemaVersion: str = "openclaw-plugin-hook-v1"


class ToolRef(CanonicalModel):
    name: str
    params: Any = None


class ExecutionContext(CanonicalModel):
    agentId: str | None = None
    sessionKey: str | None = None
    sessionId: str | None = None
    runId: str | None = None
    toolCallId: str | None = None


class SourceRef(CanonicalModel):
    pluginId: str


class PolicyReason(CanonicalModel):
    code: str
    message: str
    category: str = "policy"


class PolicyTrace(CanonicalModel):
    policyId: str | None = None
    ruleId: str | None = None
    ruleVersion: str | None = None


class ApprovalRequestSpec(CanonicalModel):
    title: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"
    timeoutMs: int = Field(default=120_000, ge=1)
    timeoutBehavior: Literal["allow", "deny"] = "deny"
    approvalScope: Literal["once", "always"] = "once"


class PolicyEvaluation(CanonicalModel):
    disposition: Literal["allow", "block", "require_approval"]
    reasons: list[PolicyReason] = Field(default_factory=list)
    policyTrace: PolicyTrace | None = None
    annotations: dict[str, Any] | None = None
    approval: ApprovalRequestSpec | None = None


class ToolCallObservedData(CanonicalModel):
    tool: ToolRef
    executionContext: ExecutionContext
    sourceRef: SourceRef


class DecisionRecordedData(CanonicalModel):
    decisionId: str = Field(default_factory=new_id)
    disposition: Literal["allow", "block", "require_approval"]
    reasons: list[PolicyReason] = Field(default_factory=list)
    policyTrace: PolicyTrace | None = None
    annotations: dict[str, Any] | None = None


class ApprovalRequestedData(CanonicalModel):
    approvalRequestId: str = Field(default_factory=new_id)
    decisionId: str
    title: str
    description: str
    severity: Literal["info", "warning", "critical"] = "warning"
    timeoutMs: int = Field(default=120_000, ge=1)
    timeoutBehavior: Literal["allow", "deny"] = "deny"
    approvalScope: Literal["once", "always"] = "once"
    status: Literal["pending"] = "pending"


class ExecutionSuspendedData(CanonicalModel):
    suspensionId: str = Field(default_factory=new_id)
    approvalRequestId: str
    suspensionReason: Literal["approval_required"] = "approval_required"
    resumeCondition: Literal["approval_resolved_positive"] = "approval_resolved_positive"


class ResolvedBy(CanonicalModel):
    actorType: Literal["user", "system", "channel", "unknown"] = "unknown"
    actorId: str | None = None
    displayName: str | None = None


class ApprovalResolvedData(CanonicalModel):
    approvalRequestId: str
    resolution: Literal["allow_once", "allow_always", "deny", "timeout", "cancelled"]
    resolvedAt: datetime = Field(default_factory=utc_now)
    resolvedBy: ResolvedBy = Field(default_factory=ResolvedBy)


class ExecutionResumedData(CanonicalModel):
    suspensionId: str
    approvalRequestId: str
    resumeReason: Literal["approval_granted"] = "approval_granted"
    resumeMode: Literal["single_use", "persistent"]


class ExecutionDeniedData(CanonicalModel):
    suspensionId: str
    approvalRequestId: str
    denyReason: Literal["approval_denied", "approval_timeout", "approval_cancelled"]


class ToolCallCompletedData(CanonicalModel):
    outcome: Literal["success", "error", "unknown"] = "unknown"
    result: Any = None
    error: str | None = None
    durationMs: int | None = None


class GovernanceEventBase(CanonicalModel):
    eventId: str = Field(default_factory=new_id)
    schemaVersion: Literal[1] = 1
    occurredAt: datetime = Field(default_factory=utc_now)
    recordedAt: datetime = Field(default_factory=utc_now)
    correlationId: str | None = None
    causationId: str | None = None
    streamId: str
    producer: ProducerRef = Field(default_factory=ProducerRef)
    subject: GovernanceSubject
    provenance: ProvenanceRef


class ToolCallObservedEvent(GovernanceEventBase):
    eventType: Literal["governance.tool_call_observed.v1"] = "governance.tool_call_observed.v1"
    data: ToolCallObservedData


class DecisionRecordedEvent(GovernanceEventBase):
    eventType: Literal["governance.decision_recorded.v1"] = "governance.decision_recorded.v1"
    data: DecisionRecordedData


class ApprovalRequestedEvent(GovernanceEventBase):
    eventType: Literal["governance.approval_requested.v1"] = "governance.approval_requested.v1"
    data: ApprovalRequestedData


class ExecutionSuspendedEvent(GovernanceEventBase):
    eventType: Literal["governance.execution_suspended.v1"] = "governance.execution_suspended.v1"
    data: ExecutionSuspendedData


class ApprovalResolvedEvent(GovernanceEventBase):
    eventType: Literal["governance.approval_resolved.v1"] = "governance.approval_resolved.v1"
    data: ApprovalResolvedData


class ExecutionResumedEvent(GovernanceEventBase):
    eventType: Literal["governance.execution_resumed.v1"] = "governance.execution_resumed.v1"
    data: ExecutionResumedData


class ExecutionDeniedEvent(GovernanceEventBase):
    eventType: Literal["governance.execution_denied.v1"] = "governance.execution_denied.v1"
    data: ExecutionDeniedData


class ToolCallCompletedEvent(GovernanceEventBase):
    eventType: Literal["governance.tool_call_completed.v1"] = "governance.tool_call_completed.v1"
    data: ToolCallCompletedData


CanonicalGovernanceEvent = (
    ToolCallObservedEvent
    | DecisionRecordedEvent
    | ApprovalRequestedEvent
    | ExecutionSuspendedEvent
    | ApprovalResolvedEvent
    | ExecutionResumedEvent
    | ExecutionDeniedEvent
    | ToolCallCompletedEvent
)


class ApprovalRow(TypedDict):
    approvalRequestId: str
    governanceCallId: str
    decisionId: str
    requestedEventId: str
    suspensionId: str
    status: str
    requestedAt: str
    projection: dict[str, Any]
    toolCallId: str | None
    sessionId: str | None
    toolName: str | None
    workflowRunId: NotRequired[str]
    workflowId: NotRequired[str]
    suspendedNodeId: NotRequired[str]
    suspendedTokenId: NotRequired[str]
    runtimeConversationId: NotRequired[str]
    runtimeTurnNodeId: NotRequired[str]
    runtimeProjection: NotRequired[dict[str, Any]]
    gatewayApprovalId: NotRequired[str]
    resolvedAt: NotRequired[str]


class GatewayApprovalRequestRef(TypedDict, total=False):
    toolName: str
    toolCallId: str
    sessionKey: str


class GatewayApprovalRequestedPayload(TypedDict):
    id: str
    request: GatewayApprovalRequestRef
    createdAtMs: int | None
    expiresAtMs: int | None


class GatewayApprovalResolvedPayload(TypedDict, total=False):
    id: str
    request: GatewayApprovalRequestRef
    decision: str
    resolvedBy: str
    ts: int | None


class GatewayApprovalRow(TypedDict):
    gatewayApprovalId: str
    kind: str
    status: str
    request: GatewayApprovalRequestRef
    createdAtMs: NotRequired[int | None]
    expiresAtMs: NotRequired[int | None]
    decision: NotRequired[str | None]
    resolvedBy: NotRequired[str | None]
    ts: NotRequired[int | None]
    bridgeApprovalId: NotRequired[str]


class WorkflowRunRow(TypedDict, total=False):
    governanceCallId: str
    workflowId: str
    runId: str
    conversationId: str
    turnNodeId: str
    status: str
    decision: str
    finalDisposition: str
    approvalResolution: str
    suspendedNodeId: str
    suspendedTokenId: str
    projection: dict[str, Any]


class GovernanceProjectionRow(TypedDict, total=False):
    governanceCallId: str
    proposalNodeId: str
    decisionNodeId: str
    approvalNodeId: str
    resolutionNodeId: str
    completionNodeId: str
    completionOutcome: str


class ApprovalSubscriptionStatusRow(TypedDict):
    enabled: bool
    started: bool
    connected: bool
    lastError: str | None
    lastRequestedEventAt: int | None
    lastResolvedEventAt: int | None
    lastStatusAt: int | None


class ApprovalRuntimeAttachmentRow(TypedDict, total=False):
    workflowId: str | None
    workflowRunId: str | None
    runtimeConversationId: str | None
    runtimeTurnNodeId: str | None
    suspendedNodeId: str | None
    suspendedTokenId: str | None
    runtimeProjection: dict[str, Any]


DebugStateSnapshot: TypeAlias = dict[str, Any]
