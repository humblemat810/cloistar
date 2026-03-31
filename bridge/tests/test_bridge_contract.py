from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from bridge.app.main import app
from bridge.app.store import store


class BridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.client = TestClient(app)

    def test_before_tool_call_blocks_destructive_command(self) -> None:
        response = self.client.post(
            "/policy/before-tool-call",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-1",
                "toolName": "exec",
                "params": {"command": "rm -rf /"},
                "rawEvent": {"kind": "before_tool_call"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "decision": "block",
                "reason": "Blocked by policy marker: rm -rf",
            },
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["events"][0]["type"], "tool_call_proposed")
        self.assertEqual(snapshot["events"][1]["type"], "tool_call_blocked")

    def test_before_tool_call_requests_approval_for_dangerous_tool(self) -> None:
        response = self.client.post(
            "/policy/before-tool-call",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-2",
                "toolName": "exec",
                "params": {"command": "echo hello"},
                "rawEvent": {"kind": "before_tool_call"},
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["decision"], "requireApproval")
        self.assertEqual(payload["title"], "Approval required for exec")
        self.assertIn("approvalId", payload)

        snapshot = store.snapshot()
        self.assertIn(payload["approvalId"], snapshot["approvals"])
        self.assertEqual(
            snapshot["events"][-1]["type"], "tool_call_approval_requested"
        )

    def test_after_tool_call_records_completion_event(self) -> None:
        response = self.client.post(
            "/events/after-tool-call",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-3",
                "toolName": "exec",
                "params": {"command": "echo hello"},
                "result": {"exitCode": 0},
                "rawEvent": {"kind": "after_tool_call"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(store.snapshot()["events"][-1]["type"], "tool_call_completed")

    def test_approval_resolution_updates_pending_approval(self) -> None:
        decision_response = self.client.post(
            "/policy/before-tool-call",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-4",
                "toolName": "exec",
                "params": {"command": "echo hello"},
                "rawEvent": {"kind": "before_tool_call"},
            },
        )
        approval_id = decision_response.json()["approvalId"]

        response = self.client.post(
            "/approval/resolution",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-4",
                "toolName": "exec",
                "approvalId": approval_id,
                "resolution": "approved",
                "rawEvent": {"kind": "approval_resolution"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(store.snapshot()["approvals"][approval_id]["status"], "approved")

    def test_approval_resolution_for_unknown_id_returns_404(self) -> None:
        response = self.client.post(
            "/approval/resolution",
            json={
                "pluginId": "kogwistar-governance",
                "sessionId": "sess-5",
                "toolName": "exec",
                "approvalId": "missing-approval",
                "resolution": "approved",
                "rawEvent": {"kind": "approval_resolution"},
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "approval not found")


if __name__ == "__main__":
    unittest.main()
