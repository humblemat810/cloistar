#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS="${1:-15}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: missing python interpreter at ${PYTHON_BIN}" >&2
  exit 1
fi

if ! command -v timeout >/dev/null 2>&1; then
  echo "error: 'timeout' command is required" >&2
  exit 1
fi

cd "${REPO_ROOT}"

echo "Running native governance resume probe with ${TIMEOUT_SECONDS}s outer timeout"

timeout --signal=TERM --kill-after=5s "${TIMEOUT_SECONDS}s" \
  env PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1 \
  "${PYTHON_BIN}" - <<'PY'
import faulthandler
import json
from bridge.app.integrations.openclaw_dto import OpenClawBeforeToolCallPayload
from bridge.app.integrations.openclaw_mapper import build_receipt, canonicalize_before_tool_call
from bridge.app.policy import decide
from bridge.app.runtime import reset_governance_runtime_host
from bridge.app.runtime.governance_runtime import get_governance_runtime_host
from bridge.app.store import store
from bridge.tests.test_bridge_contract import load_fixture

faulthandler.enable()
faulthandler.dump_traceback_later(10, repeat=False)

reset_governance_runtime_host()
store.reset()
host = get_governance_runtime_host()

raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
payload = OpenClawBeforeToolCallPayload.model_validate(raw)
receipt = build_receipt("before_tool_call", payload)
observed = canonicalize_before_tool_call(payload, receipt)

print("[1/3] evaluating proposal")
decision = host.evaluate_proposal(observed, policy_evaluator=decide, store=store)
print(json.dumps({
    "status": decision.workflow.get("status"),
    "decision": decision.workflow.get("decision"),
    "runId": decision.workflow.get("runId"),
    "suspendedNodeId": decision.workflow.get("suspendedNodeId"),
    "suspendedTokenId": decision.workflow.get("suspendedTokenId"),
}, indent=2))

approval_row = {
    "approvalRequestId": "probe-approval-1",
    "governanceCallId": observed.subject.governanceCallId,
    "workflowId": decision.workflow.get("workflowId"),
    "workflowRunId": decision.workflow.get("runId"),
    "runtimeConversationId": decision.workflow.get("conversationId"),
    "runtimeTurnNodeId": decision.workflow.get("turnNodeId"),
    "suspendedNodeId": decision.workflow.get("suspendedNodeId"),
    "suspendedTokenId": decision.workflow.get("suspendedTokenId"),
    "runtimeProjection": dict(decision.projection or {}),
}

print("[2/3] resuming approval")
resume = host.resume_approval(
    approval_row,
    resolution="allow_once",
    resolved_at="2026-04-01T00:00:00+00:00",
)

if resume is None:
    print("resume returned null")
    raise SystemExit(2)

print("[3/3] resumed")
print(json.dumps({
    "status": resume.workflow.get("status"),
    "finalDisposition": resume.workflow.get("finalDisposition"),
    "approvalResolution": resume.workflow.get("approvalResolution"),
    "projectionKeys": sorted((resume.projection or {}).keys()),
}, indent=2))
PY
