from __future__ import annotations

"""Unit tests for the durable governance persistence facade."""

import os
import tempfile
import unittest

from bridge.app.runtime import GovernanceService, get_governance_runtime_host, reset_governance_runtime_host
from bridge.tests.test_bridge_contract import load_fixture


class GovernanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="gov-service-")
        self._previous_runtime_dir = os.environ.get("KOGWISTAR_RUNTIME_DATA_DIR")
        os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = self._temp_dir.name
        reset_governance_runtime_host()
        host = get_governance_runtime_host()
        self.service = GovernanceService.from_engine(
            host.conversation_engine,
            workflow_engine=host.workflow_engine,
        )
        self.service.reset_store()

    def tearDown(self) -> None:
        self.service.reset_store()
        reset_governance_runtime_host()
        if self._previous_runtime_dir is None:
            os.environ.pop("KOGWISTAR_RUNTIME_DATA_DIR", None)
        else:
            os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = self._previous_runtime_dir
        self._temp_dir.cleanup()

    def test_materialize_debug_snapshot_from_durable_rows(self) -> None:
        observed_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        event_ts = "2026-04-02T00:00:00Z"
        governance_call_id = "gov-call-1"
        observed_event["eventId"] = "event-observed-1"
        observed_event["occurredAt"] = event_ts
        observed_event["recordedAt"] = event_ts
        observed_event["subject"] = {"governanceCallId": governance_call_id, "approvalRequestId": None}
        receipt = {
            "receiptId": "receipt-1",
            "receivedAt": event_ts,
            "sourceSystem": "openclaw",
            "sourceEventType": "before_tool_call",
            "adapterVersion": "v1",
            "payloadSha256": "abc",
            "payload": {"sessionId": "approval-demo", "rawEvent": {"toolCallId": "tool-1"}},
            "parseStatus": "accepted",
            "notes": [],
        }
        approval_row = {
            "approvalRequestId": "approval-1",
            "governanceCallId": governance_call_id,
            "decisionId": "decision-1",
            "requestedEventId": "event-approval-1",
            "suspensionId": "suspend-1",
            "status": "pending",
            "requestedAt": event_ts,
            "projection": {"title": "Approval required for exec"},
            "toolCallId": "tool-1",
            "sessionId": observed_event["correlationId"],
            "toolName": "exec",
            "workflowRunId": "govrun:1",
            "suspendedTokenId": "govrun:1",
        }
        gateway_row = {
            "gatewayApprovalId": "plugin:approval-1",
            "kind": "plugin",
            "status": "pending",
            "request": {"toolCallId": "tool-1", "toolName": "exec"},
            "bridgeApprovalId": "approval-1",
        }
        workflow_row = {
            "workflowId": "kogwistar.governance.openclaw.v1",
            "runId": "govrun:1",
            "status": "suspended",
            "decision": "require_approval",
        }
        projection_row = {
            "proposalNodeId": "gov|govrun:1|proposal",
            "decisionNodeId": "gov|govrun:1|decision",
            "approvalNodeId": "gov|govrun:1|approval",
        }

        self.service.persist_event_row(observed_event)
        self.service.persist_receipt_row(receipt)
        self.service.upsert_approval_row("approval-1", approval_row)
        self.service.upsert_gateway_approval_row("plugin:approval-1", gateway_row)
        self.service.upsert_workflow_run_row(governance_call_id, workflow_row)
        self.service.upsert_projection_row(governance_call_id, projection_row)
        self.service.upsert_approval_subscription_row(
            {
                "enabled": True,
                "started": True,
                "connected": True,
                "lastError": None,
                "lastRequestedEventAt": 123,
                "lastResolvedEventAt": None,
                "lastStatusAt": 123,
            }
        )

        snapshot = self.service.materialize_debug_snapshot()
        self.assertEqual(snapshot["events"][0]["eventType"], "governance.tool_call_observed.v1")
        self.assertIn("approval-1", snapshot["approvals"])
        self.assertIn("plugin:approval-1", snapshot["gatewayApprovals"])
        self.assertEqual(
            snapshot["workflowRuns"][governance_call_id]["status"],
            "suspended",
        )
        self.assertEqual(
            snapshot["governanceProjection"][governance_call_id]["approvalNodeId"],
            "gov|govrun:1|approval",
        )
        self.assertEqual(snapshot["approvalSubscription"]["connected"], True)
        self.assertEqual(self.service.count_matching_approvals("exec"), 1)
