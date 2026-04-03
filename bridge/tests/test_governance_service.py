from __future__ import annotations

"""Unit tests for the durable governance persistence facade."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from bridge.app.integrations.openclaw_dto import OpenClawBeforeToolCallPayload
from bridge.app.integrations.openclaw_mapper import build_receipt, canonicalize_before_tool_call
from bridge.app.policy import decide
from bridge.app.runtime import GovernanceService, get_governance_runtime_host, reset_governance_runtime_host
from bridge.app.store import store


FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str):
    return json.loads((FIXTURES.joinpath(*parts)).read_text())


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

    def test_backbone_steps_get_scoped_sequence_metadata(self) -> None:
        observed_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        event_ts = "2026-04-03T00:00:00Z"
        governance_call_id = "gov-call-seq-1"
        observed_event["eventId"] = "event-observed-seq-1"
        observed_event["occurredAt"] = event_ts
        observed_event["recordedAt"] = event_ts
        observed_event["subject"] = {"governanceCallId": governance_call_id, "approvalRequestId": None}

        self.service.persist_event_row(observed_event)

        waiting_input = self._node_metadata(f"govbackbone|{governance_call_id}|waiting_input")
        input_received = self._node_metadata(f"govbackbone|{governance_call_id}|input_received")
        self.assertEqual(waiting_input["entity_type"], "governance_backbone_step")
        self.assertEqual(input_received["entity_type"], "governance_backbone_step")
        self.assertEqual(waiting_input["seq"], 1)
        self.assertEqual(input_received["seq"], 2)
        self.assertEqual(
            self.service.conversation_engine.meta_sqlite.current_scoped_seq(f"governance:{governance_call_id}"),
            2,
        )

    def test_runtime_governance_nodes_get_scoped_sequence_metadata(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.block.json")
        payload = OpenClawBeforeToolCallPayload.model_validate(raw)
        receipt = build_receipt("before_tool_call", payload)
        observed_event = canonicalize_before_tool_call(payload, receipt)
        governance_call_id = observed_event.subject.governanceCallId
        runtime_decision = get_governance_runtime_host().evaluate_proposal(
            observed_event,
            policy_evaluator=decide,
            store=store,
        )

        proposal_md = self._node_metadata(runtime_decision.projection["proposalNodeId"])
        decision_md = self._node_metadata(runtime_decision.projection["decisionNodeId"])
        self.assertEqual(proposal_md["entity_type"], "governance_proposal")
        self.assertEqual(decision_md["entity_type"], "governance_decision")
        self.assertEqual(proposal_md["seq"], 1)
        self.assertEqual(decision_md["seq"], 2)
        self.assertEqual(
            self.service.conversation_engine.meta_sqlite.current_scoped_seq(f"governance:{governance_call_id}"),
            2,
        )

    def _node_metadata(self, node_id: str) -> dict:
        got = self.service.conversation_engine.backend.node_get(ids=[node_id], include=["metadatas"])
        self.assertTrue(got["ids"], f"missing node {node_id}")
        metadatas = got.get("metadatas") or []
        self.assertTrue(metadatas, f"missing metadata for node {node_id}")
        metadata = metadatas[0]
        self.assertIsInstance(metadata, dict)
        return metadata
