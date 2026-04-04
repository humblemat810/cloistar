from __future__ import annotations

from .governance_models import (
    ApprovalRequestedEvent,
    ApprovalResolvedEvent,
    CanonicalGovernanceEvent,
    ExecutionDeniedEvent,
    ExecutionResumedEvent,
    GovernanceCompletedEvent,
    GovernanceResultRecordedEvent,
)
from typing import Any


def append_event(store: Any, event: CanonicalGovernanceEvent) -> dict:
    return store.append_canonical_event(event)


def register_approval_request(store: Any, event: ApprovalRequestedEvent, suspension_id: str) -> dict:
    return store.register_approval_request(event, suspension_id)


def append_approval_resolution(
    store: Any,
    resolved_event: ApprovalResolvedEvent,
    follow_up_event: ExecutionResumedEvent | ExecutionDeniedEvent,
    *,
    result_event: GovernanceResultRecordedEvent | None = None,
    completed_event: GovernanceCompletedEvent | None = None,
) -> dict | None:
    approval = store.resolve_approval(
        resolved_event.data.approvalRequestId,
        resolved_event.data.resolution,
        resolved_event.data.resolvedAt.isoformat(),
    )
    if approval is None:
        return None

    store.append_canonical_event(resolved_event)
    store.append_canonical_event(follow_up_event)
    if result_event is not None:
        store.append_canonical_event(result_event)
    if completed_event is not None:
        store.append_canonical_event(completed_event)
    return approval
