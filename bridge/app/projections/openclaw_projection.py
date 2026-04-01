from __future__ import annotations

from ..domain.governance_models import PolicyEvaluation
from ..integrations.openclaw_dto import (
    OpenClawAllowDecision,
    OpenClawBlockDecision,
    OpenClawDecision,
    OpenClawRequireApprovalDecision,
)


def project_decision(
    evaluation: PolicyEvaluation,
    approval_id: str | None = None,
) -> OpenClawDecision:
    if evaluation.disposition == "allow":
        return OpenClawAllowDecision(annotations=evaluation.annotations)

    if evaluation.disposition == "block":
        reason = "Blocked by policy"
        if evaluation.reasons:
            reason = evaluation.reasons[0].message
        return OpenClawBlockDecision(reason=reason)

    approval = evaluation.approval
    if approval is None:
        raise ValueError("approval projection requires approval details")

    return OpenClawRequireApprovalDecision(
        title=approval.title,
        description=approval.description,
        severity=approval.severity,
        timeoutMs=approval.timeoutMs,
        timeoutBehavior=approval.timeoutBehavior,
        approvalId=approval_id,
    )
