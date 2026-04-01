from __future__ import annotations

from .governance_models import (
    ApprovalRequestedEvent,
    ApprovalResolvedEvent,
    CanonicalGovernanceEvent,
    ExecutionDeniedEvent,
    ExecutionResumedEvent,
)
from ..store import InMemoryStore


def append_event(store: InMemoryStore, event: CanonicalGovernanceEvent) -> dict:
    return store.append_canonical_event(event)


def register_approval_request(store: InMemoryStore, event: ApprovalRequestedEvent, suspension_id: str) -> dict:
    return store.register_approval_request(event, suspension_id)


def append_approval_resolution(
    store: InMemoryStore,
    resolved_event: ApprovalResolvedEvent,
    follow_up_event: ExecutionResumedEvent | ExecutionDeniedEvent,
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
    return approval
