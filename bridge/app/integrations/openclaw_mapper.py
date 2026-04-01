from __future__ import annotations

from typing import Any

from ..domain.governance_models import (
    ApprovalRequestSpec,
    ApprovalRequestedData,
    ApprovalRequestedEvent,
    ApprovalResolvedData,
    ApprovalResolvedEvent,
    CanonicalGovernanceEvent,
    DecisionRecordedData,
    DecisionRecordedEvent,
    ExecutionContext,
    ExecutionDeniedData,
    ExecutionDeniedEvent,
    ExecutionResumedData,
    ExecutionResumedEvent,
    ExecutionSuspendedData,
    ExecutionSuspendedEvent,
    GovernanceSubject,
    IntegrationReceipt,
    PolicyEvaluation,
    ProvenanceRef,
    SourceRef,
    ToolCallCompletedData,
    ToolCallCompletedEvent,
    ToolCallObservedData,
    ToolCallObservedEvent,
    ToolRef,
    payload_digest,
    stable_governance_call_id,
)
from .openclaw_dto import (
    OpenClawAfterToolCallPayload,
    OpenClawApprovalResolutionPayload,
    OpenClawBeforeToolCallPayload,
)


def build_receipt(source_event_type: str, payload: Any) -> IntegrationReceipt:
    dumped = payload.model_dump(mode="json")
    return IntegrationReceipt(
        sourceEventType=source_event_type,
        payloadSha256=payload_digest(dumped),
        payload=dumped,
    )


def canonicalize_before_tool_call(
    payload: OpenClawBeforeToolCallPayload,
    receipt: IntegrationReceipt,
) -> ToolCallObservedEvent:
    execution_context = _execution_context(payload)
    governance_call_id = _governance_call_id(payload, execution_context)

    return ToolCallObservedEvent(
        occurredAt=receipt.receivedAt,
        recordedAt=receipt.receivedAt,
        correlationId=execution_context.runId or payload.sessionId,
        streamId=_stream_id(governance_call_id),
        subject=GovernanceSubject(governanceCallId=governance_call_id),
        provenance=_provenance("before_tool_call", receipt),
        data=ToolCallObservedData(
            tool=ToolRef(name=payload.toolName or "", params=payload.params),
            executionContext=execution_context,
            sourceRef=SourceRef(pluginId=payload.pluginId),
        ),
    )


def decision_event_from_policy(
    observed_event: ToolCallObservedEvent,
    evaluation: PolicyEvaluation,
) -> DecisionRecordedEvent:
    return DecisionRecordedEvent(
        occurredAt=observed_event.recordedAt,
        recordedAt=observed_event.recordedAt,
        correlationId=observed_event.correlationId,
        causationId=observed_event.eventId,
        streamId=observed_event.streamId,
        subject=observed_event.subject,
        provenance=observed_event.provenance,
        data=DecisionRecordedData(
            disposition=evaluation.disposition,
            reasons=evaluation.reasons,
            policyTrace=evaluation.policyTrace,
            annotations=evaluation.annotations,
        ),
    )


def approval_events_from_policy(
    decision_event: DecisionRecordedEvent,
    approval: ApprovalRequestSpec,
) -> tuple[ApprovalRequestedEvent, ExecutionSuspendedEvent]:
    approval_event = ApprovalRequestedEvent(
        occurredAt=decision_event.recordedAt,
        recordedAt=decision_event.recordedAt,
        correlationId=decision_event.correlationId,
        causationId=decision_event.eventId,
        streamId=decision_event.streamId,
        subject=GovernanceSubject(governanceCallId=decision_event.subject.governanceCallId),
        provenance=decision_event.provenance,
        data=ApprovalRequestedData(
            decisionId=decision_event.data.decisionId,
            title=approval.title,
            description=approval.description,
            severity=approval.severity,
            timeoutMs=approval.timeoutMs,
            timeoutBehavior=approval.timeoutBehavior,
            approvalScope=approval.approvalScope,
        ),
    )
    suspended_event = ExecutionSuspendedEvent(
        occurredAt=decision_event.recordedAt,
        recordedAt=decision_event.recordedAt,
        correlationId=decision_event.correlationId,
        causationId=approval_event.eventId,
        streamId=decision_event.streamId,
        subject=GovernanceSubject(
            governanceCallId=decision_event.subject.governanceCallId,
            approvalRequestId=approval_event.data.approvalRequestId,
        ),
        provenance=decision_event.provenance,
        data=ExecutionSuspendedData(approvalRequestId=approval_event.data.approvalRequestId),
    )
    approval_event.subject.approvalRequestId = approval_event.data.approvalRequestId
    return approval_event, suspended_event


def canonicalize_after_tool_call(
    payload: OpenClawAfterToolCallPayload,
    receipt: IntegrationReceipt,
) -> ToolCallCompletedEvent:
    execution_context = _execution_context(payload)
    governance_call_id = _governance_call_id(payload, execution_context)
    outcome = "unknown"
    if payload.error:
        outcome = "error"
    elif payload.result is not None:
        outcome = "success"

    return ToolCallCompletedEvent(
        occurredAt=receipt.receivedAt,
        recordedAt=receipt.receivedAt,
        correlationId=execution_context.runId or payload.sessionId,
        streamId=_stream_id(governance_call_id),
        subject=GovernanceSubject(governanceCallId=governance_call_id),
        provenance=_provenance("after_tool_call", receipt),
        data=ToolCallCompletedData(
            outcome=outcome,
            result=payload.result,
            error=payload.error,
            durationMs=payload.durationMs or _as_int(payload.rawEvent.get("durationMs")),
        ),
    )


def canonicalize_approval_resolution(
    payload: OpenClawApprovalResolutionPayload,
    receipt: IntegrationReceipt,
    approval_request_id: str,
    governance_call_id: str,
) -> ApprovalResolvedEvent:
    correlation_id = payload.rawEvent.get("runId") or payload.sessionId
    return ApprovalResolvedEvent(
        occurredAt=receipt.receivedAt,
        recordedAt=receipt.receivedAt,
        correlationId=correlation_id,
        streamId=_stream_id(governance_call_id),
        subject=GovernanceSubject(
            governanceCallId=governance_call_id,
            approvalRequestId=approval_request_id,
        ),
        provenance=_provenance("approval_resolution", receipt),
        data=ApprovalResolvedData(
            approvalRequestId=approval_request_id,
            resolution=payload.resolution.replace("-", "_"),
        ),
    )


def follow_up_event_for_resolution(
    resolved_event: ApprovalResolvedEvent,
    suspension_id: str,
) -> CanonicalGovernanceEvent:
    if resolved_event.data.resolution in {"allow_once", "allow_always"}:
        resume_mode = "single_use"
        if resolved_event.data.resolution == "allow_always":
            resume_mode = "persistent"
        return ExecutionResumedEvent(
            occurredAt=resolved_event.recordedAt,
            recordedAt=resolved_event.recordedAt,
            correlationId=resolved_event.correlationId,
            causationId=resolved_event.eventId,
            streamId=resolved_event.streamId,
            subject=resolved_event.subject,
            provenance=resolved_event.provenance,
            data=ExecutionResumedData(
                suspensionId=suspension_id,
                approvalRequestId=resolved_event.data.approvalRequestId,
                resumeMode=resume_mode,
            ),
        )

    deny_reason = "approval_denied"
    if resolved_event.data.resolution == "timeout":
        deny_reason = "approval_timeout"
    elif resolved_event.data.resolution == "cancelled":
        deny_reason = "approval_cancelled"

    return ExecutionDeniedEvent(
        occurredAt=resolved_event.recordedAt,
        recordedAt=resolved_event.recordedAt,
        correlationId=resolved_event.correlationId,
        causationId=resolved_event.eventId,
        streamId=resolved_event.streamId,
        subject=resolved_event.subject,
        provenance=resolved_event.provenance,
        data=ExecutionDeniedData(
            suspensionId=suspension_id,
            approvalRequestId=resolved_event.data.approvalRequestId,
            denyReason=deny_reason,
        ),
    )


def _execution_context(
    payload: OpenClawBeforeToolCallPayload | OpenClawAfterToolCallPayload,
) -> ExecutionContext:
    raw = payload.rawEvent
    return ExecutionContext(
        sessionId=payload.sessionId,
        runId=_as_str(raw.get("runId")),
        toolCallId=_as_str(raw.get("toolCallId")),
    )


def _governance_call_id(
    payload: OpenClawBeforeToolCallPayload | OpenClawAfterToolCallPayload,
    execution_context: ExecutionContext,
) -> str:
    return stable_governance_call_id(
        [
            payload.pluginId,
            execution_context.sessionId,
            payload.toolName,
            execution_context.runId,
            execution_context.toolCallId,
        ]
    )


def _stream_id(governance_call_id: str) -> str:
    return f"governance/tool-call/{governance_call_id}"


def _provenance(source_event_type: str, receipt: IntegrationReceipt) -> ProvenanceRef:
    return ProvenanceRef(
        sourceEventType=source_event_type,
        receiptId=receipt.receiptId,
        payloadSha256=receipt.payloadSha256,
    )


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    return None
