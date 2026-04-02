from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from bridge.app.integrations.openclaw_dto import (
    OpenClawAfterToolCallPayload,
    OpenClawApprovalResolutionPayload,
    OpenClawBeforeToolCallPayload,
)
from bridge.app.integrations.openclaw_mapper import (
    build_receipt,
    canonicalize_after_tool_call,
    canonicalize_before_tool_call,
)
from bridge.app.main import app
from bridge.app.policy import decide
from bridge.app.projections.openclaw_projection import project_decision
from bridge.app.runtime import reset_governance_runtime_host
from bridge.app.store import store


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> Any:
    return json.loads((FIXTURES.joinpath(*parts)).read_text())


def assert_subset(test_case: unittest.TestCase, expected: Any, actual: Any) -> None:
    if isinstance(expected, dict):
        test_case.assertIsInstance(actual, dict)
        for key, value in expected.items():
            test_case.assertIn(key, actual)
            assert_subset(test_case, value, actual[key])
        return

    if isinstance(expected, list):
        test_case.assertIsInstance(actual, list)
        test_case.assertEqual(len(expected), len(actual))
        for expected_item, actual_item in zip(expected, actual):
            assert_subset(test_case, expected_item, actual_item)
        return

    test_case.assertEqual(expected, actual)


class BridgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_governance_runtime_host()

    def setUp(self) -> None:
        store.reset()
        self.client = TestClient(app)

    def test_block_fixture_maps_raw_input_to_canonical_event_and_projection(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.block.json")
        payload = OpenClawBeforeToolCallPayload.model_validate(raw)

        receipt = build_receipt("before_tool_call", payload)
        observed_event = canonicalize_before_tool_call(payload, receipt)

        expected_event = load_fixture("canonical", "before_tool_call.block.observed.json")
        assert_subset(self, expected_event, observed_event.model_dump(mode="json"))
        self.assertTrue(observed_event.subject.governanceCallId)

        evaluation = decide(payload.toolName, payload.params)
        projection = project_decision(evaluation)
        expected_projection = load_fixture("projections", "before_tool_call.block.outbound.json")
        self.assertEqual(projection.model_dump(mode="json"), expected_projection)

    def test_require_approval_fixture_maps_raw_input_to_canonical_event_and_projection(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        payload = OpenClawBeforeToolCallPayload.model_validate(raw)

        receipt = build_receipt("before_tool_call", payload)
        observed_event = canonicalize_before_tool_call(payload, receipt)

        expected_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        assert_subset(self, expected_event, observed_event.model_dump(mode="json"))

        evaluation = decide(payload.toolName, payload.params)
        projection = project_decision(evaluation, "approval-123")
        expected_projection = load_fixture(
            "projections",
            "before_tool_call.require_approval.outbound.json",
        )
        actual_projection = projection.model_dump(mode="json")
        self.assertEqual(actual_projection["approvalId"], "approval-123")
        del actual_projection["approvalId"]
        self.assertEqual(actual_projection, expected_projection)

    def test_before_tool_call_block_endpoint_appends_canonical_events(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.block.json")

        response = self.client.post("/policy/before-tool-call", json=raw)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            load_fixture("projections", "before_tool_call.block.outbound.json"),
        )

        snapshot = store.snapshot()
        self.assertEqual(
            [event["eventType"] for event in snapshot["events"]],
            [
                "governance.tool_call_observed.v1",
                "governance.decision_recorded.v1",
            ],
        )
        self.assertEqual(len(snapshot["receipts"]), 1)
        self.assertEqual(snapshot["approvals"], {})

    def test_before_tool_call_require_approval_endpoint_appends_canonical_events(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")

        response = self.client.post("/policy/before-tool-call", json=raw)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["decision"], "requireApproval")
        self.assertIn("approvalId", payload)
        self.assertEqual(payload["title"], "Approval required for exec")

        snapshot = store.snapshot()
        self.assertEqual(
            [event["eventType"] for event in snapshot["events"]],
            [
                "governance.tool_call_observed.v1",
                "governance.decision_recorded.v1",
                "governance.approval_requested.v1",
                "governance.execution_suspended.v1",
            ],
        )
        self.assertEqual(snapshot["approvals"][payload["approvalId"]]["status"], "pending")
        self.assertEqual(len(snapshot["receipts"]), 1)
        governance_call_id = snapshot["events"][0]["subject"]["governanceCallId"]
        self.assertEqual(snapshot["workflowRuns"][governance_call_id]["status"], "suspended")
        self.assertEqual(
            snapshot["governanceProjection"][governance_call_id]["proposalNodeId"].startswith("gov|"),
            True,
        )
        self.assertEqual(
            snapshot["governanceProjection"][governance_call_id]["approvalNodeId"].startswith("gov|"),
            True,
        )
        self.assertEqual(
            snapshot["approvals"][payload["approvalId"]]["workflowRunId"].startswith("govrun:"),
            True,
        )
        self.assertTrue(snapshot["approvals"][payload["approvalId"]]["suspendedTokenId"])
        self.assertIn(
            "proposalNodeId",
            snapshot["approvals"][payload["approvalId"]]["runtimeProjection"],
        )
        self.assertIn(
            "decisionNodeId",
            snapshot["approvals"][payload["approvalId"]]["runtimeProjection"],
        )
        self.assertIn(
            "approvalNodeId",
            snapshot["approvals"][payload["approvalId"]]["runtimeProjection"],
        )

    def test_gateway_plugin_approval_request_links_real_gateway_id_to_bridge_approval(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        decision_response = self.client.post("/policy/before-tool-call", json=raw)
        approval_id = decision_response.json()["approvalId"]

        gateway_payload = {
            "id": "plugin:real-gateway-id",
            "request": {
                "toolName": raw["toolName"],
                "toolCallId": raw["rawEvent"]["toolCallId"],
                "sessionKey": raw["sessionId"],
            },
            "createdAtMs": 1_775_054_560_000,
            "expiresAtMs": 1_775_054_680_000,
        }

        response = self.client.post("/gateway/plugin-approval/requested", json=gateway_payload)

        self.assertEqual(response.status_code, 200)
        snapshot = store.snapshot()
        self.assertEqual(snapshot["approvals"][approval_id]["gatewayApprovalId"], "plugin:real-gateway-id")
        self.assertEqual(
            snapshot["gatewayApprovals"]["plugin:real-gateway-id"]["bridgeApprovalId"],
            approval_id,
        )
        self.assertEqual(snapshot["approvalSubscription"]["lastRequestedEventAt"], 1_775_054_560_000)

    def test_gateway_plugin_approval_resolution_links_to_existing_bridge_approval(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        decision_response = self.client.post("/policy/before-tool-call", json=raw)
        approval_id = decision_response.json()["approvalId"]

        requested_payload = {
            "id": "plugin:real-gateway-id",
            "request": {
                "toolName": raw["toolName"],
                "toolCallId": raw["rawEvent"]["toolCallId"],
                "sessionKey": raw["sessionId"],
            },
            "createdAtMs": 1_775_054_560_000,
            "expiresAtMs": 1_775_054_680_000,
        }
        self.client.post("/gateway/plugin-approval/requested", json=requested_payload)

        resolved_payload = {
            "id": "plugin:real-gateway-id",
            "decision": "allow-once",
            "resolvedBy": "operator-cli",
            "ts": 1_775_054_565_000,
            "request": requested_payload["request"],
        }
        response = self.client.post("/gateway/plugin-approval/resolved", json=resolved_payload)

        self.assertEqual(response.status_code, 200)
        snapshot = store.snapshot()
        self.assertEqual(snapshot["approvals"][approval_id]["gatewayApprovalId"], "plugin:real-gateway-id")
        self.assertEqual(
            snapshot["gatewayApprovals"]["plugin:real-gateway-id"]["decision"],
            "allow-once",
        )
        self.assertEqual(snapshot["approvalSubscription"]["lastResolvedEventAt"], 1_775_054_565_000)

    def test_gateway_approval_subscription_status_is_visible_in_debug_state(self) -> None:
        response = self.client.post(
            "/gateway/approval-subscription/status",
            json={
                "enabled": True,
                "started": True,
                "connected": False,
                "lastError": "connect ECONNREFUSED 127.0.0.1:42097",
                "lastStatusAt": 1_775_054_550_000,
            },
        )

        self.assertEqual(response.status_code, 200)
        snapshot = store.snapshot()
        self.assertEqual(
            snapshot["approvalSubscription"],
            {
                "enabled": True,
                "started": True,
                "connected": False,
                "lastError": "connect ECONNREFUSED 127.0.0.1:42097",
                "lastRequestedEventAt": None,
                "lastResolvedEventAt": None,
                "lastStatusAt": 1_775_054_550_000,
            },
        )

    def test_after_tool_call_fixture_maps_raw_input_to_canonical_completion(self) -> None:
        raw = load_fixture("openclaw", "after_tool_call.success.json")
        payload = OpenClawAfterToolCallPayload.model_validate(raw)

        receipt = build_receipt("after_tool_call", payload)
        completed_event = canonicalize_after_tool_call(payload, receipt)

        expected_event = load_fixture("canonical", "after_tool_call.success.completed.json")
        assert_subset(self, expected_event, completed_event.model_dump(mode="json"))

    def test_approval_resolution_appends_resolution_and_resume_events(self) -> None:
        before_raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        decision_response = self.client.post("/policy/before-tool-call", json=before_raw)
        approval_id = decision_response.json()["approvalId"]

        resolution_raw = load_fixture("openclaw", "approval_resolution.allow_once.json")
        resolution_raw = deepcopy(resolution_raw)
        resolution_raw["approvalId"] = approval_id
        payload = OpenClawApprovalResolutionPayload.model_validate(resolution_raw)

        response = self.client.post("/approval/resolution", json=payload.model_dump(mode="json"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

        snapshot = store.snapshot()
        self.assertEqual(snapshot["approvals"][approval_id]["status"], "allow_once")
        self.assertEqual(
            [event["eventType"] for event in snapshot["events"][-2:]],
            [
                "governance.approval_resolved.v1",
                "governance.execution_resumed.v1",
            ],
        )
        governance_call_id = snapshot["events"][0]["subject"]["governanceCallId"]
        self.assertEqual(snapshot["workflowRuns"][governance_call_id]["status"], "succeeded")
        self.assertEqual(snapshot["workflowRuns"][governance_call_id]["finalDisposition"], "allow")
        self.assertIn("resolutionNodeId", snapshot["governanceProjection"][governance_call_id])
        self.assertIn("proposalNodeId", snapshot["governanceProjection"][governance_call_id])
        self.assertIn("decisionNodeId", snapshot["governanceProjection"][governance_call_id])
        self.assertIn("approvalNodeId", snapshot["governanceProjection"][governance_call_id])

    def test_after_tool_call_updates_governance_projection_completion_state(self) -> None:
        before_raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        decision_response = self.client.post("/policy/before-tool-call", json=before_raw)
        approval_id = decision_response.json()["approvalId"]

        resolution_raw = load_fixture("openclaw", "approval_resolution.allow_once.json")
        resolution_raw = deepcopy(resolution_raw)
        resolution_raw["approvalId"] = approval_id
        self.client.post("/approval/resolution", json=resolution_raw)

        after_raw = load_fixture("openclaw", "after_tool_call.success.json")
        after_raw = deepcopy(after_raw)
        after_raw["sessionId"] = before_raw["sessionId"]
        after_raw["toolName"] = before_raw["toolName"]
        after_raw["params"] = deepcopy(before_raw["params"])
        after_raw["rawEvent"]["toolName"] = before_raw["rawEvent"]["toolName"]
        after_raw["rawEvent"]["params"] = deepcopy(before_raw["rawEvent"]["params"])
        after_raw["rawEvent"]["runId"] = before_raw["rawEvent"]["runId"]
        after_raw["rawEvent"]["toolCallId"] = before_raw["rawEvent"]["toolCallId"]
        response = self.client.post("/events/after-tool-call", json=after_raw)

        self.assertEqual(response.status_code, 200)
        governance_call_id = store.snapshot()["events"][0]["subject"]["governanceCallId"]
        snapshot = store.snapshot()
        self.assertEqual(snapshot["workflowRuns"][governance_call_id]["status"], "completed")
        self.assertEqual(
            snapshot["governanceProjection"][governance_call_id]["completionOutcome"],
            "success",
        )
        self.assertIn("completionNodeId", snapshot["governanceProjection"][governance_call_id])

    def test_approval_resolution_for_unknown_id_returns_404(self) -> None:
        raw = load_fixture("openclaw", "approval_resolution.allow_once.json")
        raw = deepcopy(raw)
        raw["approvalId"] = "missing-approval"

        response = self.client.post("/approval/resolution", json=raw)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "approval not found")

    def test_require_approval_persists_across_runtime_host_restart(self) -> None:
        previous = os.environ.get("KOGWISTAR_RUNTIME_DATA_DIR")
        with tempfile.TemporaryDirectory(prefix="bridge-persist-") as temp_dir:
            os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = temp_dir
            reset_governance_runtime_host()
            store.reset()
            client = TestClient(app)

            before_raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
            decision_response = client.post("/policy/before-tool-call", json=before_raw)
            approval_id = decision_response.json()["approvalId"]
            snapshot_before = store.snapshot()

            reset_governance_runtime_host()
            snapshot_after_restart = store.snapshot()
            self.assertIn(approval_id, snapshot_after_restart["approvals"])
            self.assertEqual(
                [event["eventType"] for event in snapshot_after_restart["events"]],
                [event["eventType"] for event in snapshot_before["events"]],
            )

            resolution_raw = deepcopy(load_fixture("openclaw", "approval_resolution.allow_once.json"))
            resolution_raw["approvalId"] = approval_id
            resolution_response = client.post("/approval/resolution", json=resolution_raw)

            self.assertEqual(resolution_response.status_code, 200)
            self.assertEqual(store.snapshot()["approvals"][approval_id]["status"], "allow_once")

        if previous is None:
            os.environ.pop("KOGWISTAR_RUNTIME_DATA_DIR", None)
        else:
            os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = previous
        reset_governance_runtime_host()


if __name__ == "__main__":
    unittest.main()
