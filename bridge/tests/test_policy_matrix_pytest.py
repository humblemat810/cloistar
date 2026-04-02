from __future__ import annotations

"""Fast bridge integration policy matrix.

This suite runs entirely in-process with FastAPI ``TestClient`` and does not
start the external OpenClaw helper, gateway, or agent CLI.

Run it with:

```bash
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_policy_matrix_pytest.py -q
```

Cases covered:

- ``policy_approval``: allow path
- ``policy_reject``: block path
- ``require_approval``: requireApproval path
"""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from bridge.app.main import app
from bridge.app.runtime import reset_governance_runtime_host
from bridge.app.store import store
from bridge.tests.test_bridge_contract import load_fixture


def make_allow_payload() -> dict:
    return {
        "pluginId": "kogwistar-governance",
        "sessionId": "allow-demo-pytest",
        "toolName": "read",
        "params": {
            "path": "/tmp/proof.txt",
        },
        "rawEvent": {
            "toolName": "read",
            "params": {
                "path": "/tmp/proof.txt",
            },
            "runId": "pytest-run-allow",
            "toolCallId": "pytest-toolcall-allow",
        },
    }


@pytest.fixture(autouse=True)
def reset_bridge_state():
    reset_governance_runtime_host()
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("case_id", "raw_payload", "expected_decision", "expected_events"),
    [
        (
            "policy_approval",
            make_allow_payload(),
            {
                "decision": "allow",
                "annotations": {"policy": "allow-default"},
            },
            [
                "governance.tool_call_observed.v1",
                "governance.decision_recorded.v1",
            ],
        ),
        (
            "policy_reject",
            load_fixture("openclaw", "before_tool_call.block.json"),
            load_fixture("projections", "before_tool_call.block.outbound.json"),
            [
                "governance.tool_call_observed.v1",
                "governance.decision_recorded.v1",
            ],
        ),
        (
            "require_approval",
            load_fixture("openclaw", "before_tool_call.require_approval.json"),
            {
                "decision": "requireApproval",
                "title": "Approval required for exec",
                "description": "This tool is marked dangerous and requires explicit approval.",
                "severity": "warning",
                "timeoutMs": 600000,
                "timeoutBehavior": "deny",
            },
            [
                "governance.tool_call_observed.v1",
                "governance.decision_recorded.v1",
                "governance.approval_requested.v1",
                "governance.execution_suspended.v1",
            ],
        ),
    ],
    ids=lambda case_id: case_id,
)
def test_before_tool_call_policy_matrix(
    client: TestClient,
    case_id: str,
    raw_payload: dict,
    expected_decision: dict,
    expected_events: list[str],
) -> None:
    response = client.post("/policy/before-tool-call", json=deepcopy(raw_payload))

    assert response.status_code == 200
    payload = response.json()
    for key, value in expected_decision.items():
        assert payload[key] == value

    snapshot = store.snapshot()
    assert [event["eventType"] for event in snapshot["events"]] == expected_events
    assert len(snapshot["receipts"]) == 1

    if case_id == "require_approval":
        approval_id = payload["approvalId"]
        assert approval_id
        assert snapshot["approvals"][approval_id]["status"] == "pending"
        governance_call_id = snapshot["events"][0]["subject"]["governanceCallId"]
        workflow_run = snapshot["workflowRuns"][governance_call_id]
        assert workflow_run["status"] == "suspended"
        assert workflow_run["decision"] == "require_approval"
        assert snapshot["governanceProjection"][governance_call_id]["approvalNodeId"].startswith("gov|")
        return

    assert "approvalId" not in payload
    assert snapshot["approvals"] == {}
    governance_call_id = snapshot["events"][0]["subject"]["governanceCallId"]
    workflow_run = snapshot["workflowRuns"][governance_call_id]
    assert workflow_run["status"] == "succeeded"
    if case_id == "policy_approval":
        assert workflow_run["finalDisposition"] == "allow"
    else:
        assert workflow_run["finalDisposition"] == "block"
