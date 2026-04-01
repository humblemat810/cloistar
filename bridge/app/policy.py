from __future__ import annotations

import os
import re
from typing import Any

from .domain.governance_models import (
    ApprovalRequestSpec,
    PolicyEvaluation,
    PolicyReason,
    PolicyTrace,
)

DANGEROUS_TOOLS = {
    item.strip() for item in os.getenv("DANGEROUS_TOOLS", "exec,apply_patch").split(",") if item.strip()
}
BLOCK_PATTERNS = [
    item.strip().lower() for item in os.getenv("BLOCK_PATTERNS", "rm -rf,shutdown,reboot").split(",") if item.strip()
]
APPROVAL_PATTERNS = [
    item.strip().lower()
    for item in os.getenv("APPROVAL_PATTERNS", "delete,drop,truncate,chmod 777").split(",")
    if item.strip()
]
APPROVAL_TIMEOUT_MS = max(1, min(int(os.getenv("APPROVAL_TIMEOUT_MS", "600000")), 600000))


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def decide(tool_name: str | None, params: Any) -> PolicyEvaluation:
    tool = (tool_name or "").strip()
    blob = _flatten(params)

    for marker in BLOCK_PATTERNS:
        if marker and marker in blob:
            marker_slug = _slug(marker)
            return PolicyEvaluation(
                disposition="block",
                reasons=[
                    PolicyReason(
                        code=f"policy.marker.{marker_slug}",
                        message=f"Blocked by policy marker: {marker}",
                    )
                ],
                policyTrace=PolicyTrace(
                    policyId="default-governance",
                    ruleId=f"block-pattern-{marker_slug}",
                    ruleVersion="v1",
                ),
            )

    if tool in DANGEROUS_TOOLS:
        tool_slug = _slug(tool)
        return PolicyEvaluation(
            disposition="require_approval",
            reasons=[
                PolicyReason(
                    code="policy.tool.requires_approval",
                    message="Tool marked dangerous",
                )
            ],
            policyTrace=PolicyTrace(
                policyId="default-governance",
                ruleId=f"dangerous-tool-{tool_slug}",
                ruleVersion="v1",
            ),
            approval=ApprovalRequestSpec(
                title=f"Approval required for {tool}",
                description="This tool is marked dangerous and requires explicit approval.",
                severity="warning",
                timeoutMs=APPROVAL_TIMEOUT_MS,
            ),
        )

    for marker in APPROVAL_PATTERNS:
        if marker and marker in blob:
            marker_slug = _slug(marker)
            return PolicyEvaluation(
                disposition="require_approval",
                reasons=[
                    PolicyReason(
                        code=f"policy.approval_marker.{marker_slug}",
                        message=f"Request matched approval marker: {marker}",
                    )
                ],
                policyTrace=PolicyTrace(
                    policyId="default-governance",
                    ruleId=f"approval-pattern-{marker_slug}",
                    ruleVersion="v1",
                ),
                approval=ApprovalRequestSpec(
                    title="Approval required",
                    description=f"Request matched approval marker: {marker}",
                    severity="warning",
                    timeoutMs=APPROVAL_TIMEOUT_MS,
                ),
            )

    return PolicyEvaluation(
        disposition="allow",
        policyTrace=PolicyTrace(
            policyId="default-governance",
            ruleId="allow-default",
            ruleVersion="v1",
        ),
        annotations={"policy": "allow-default"},
    )
