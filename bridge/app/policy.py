from __future__ import annotations

import os
from typing import Any

from .models import AllowDecision, BlockDecision, RequireApprovalDecision

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


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower()


def decide(tool_name: str | None, params: Any) -> AllowDecision | BlockDecision | RequireApprovalDecision:
    tool = (tool_name or "").strip()
    blob = _flatten(params)

    for marker in BLOCK_PATTERNS:
        if marker and marker in blob:
            return BlockDecision(reason=f"Blocked by policy marker: {marker}")

    if tool in DANGEROUS_TOOLS:
        return RequireApprovalDecision(
            title=f"Approval required for {tool}",
            description="This tool is marked dangerous and requires explicit approval.",
            severity="warning",
        )

    for marker in APPROVAL_PATTERNS:
        if marker and marker in blob:
            return RequireApprovalDecision(
                title="Approval required",
                description=f"Request matched approval marker: {marker}",
                severity="warning",
            )

    return AllowDecision(annotations={"policy": "allow-default"})
