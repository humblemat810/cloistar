from __future__ import annotations

"""Unit tests for the durable governance persistence facade."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from bridge.app.integrations.openclaw_dto import OpenClawAfterToolCallPayload, OpenClawBeforeToolCallPayload
from bridge.app.integrations.openclaw_mapper import build_receipt, canonicalize_after_tool_call, canonicalize_before_tool_call
from bridge.app.policy import decide
from bridge.app.runtime import GovernanceService, get_governance_runtime_host, reset_governance_runtime_host
from bridge.app.store import store
from bridge.app.domain.governance_models import stable_governance_call_id


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

    def test_materialize_debug_snapshot_from_durable_records(self) -> None:
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
        approval_record = {
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
        gateway_record = {
            "gatewayApprovalId": "plugin:approval-1",
            "kind": "plugin",
            "status": "pending",
            "request": {"toolCallId": "tool-1", "toolName": "exec"},
            "bridgeApprovalId": "approval-1",
        }
        workflow_record = {
            "workflowId": "kogwistar.governance.openclaw.v1",
            "runId": "govrun:1",
            "status": "suspended",
            "decision": "require_approval",
        }
        projection_record = {
            "proposalNodeId": "gov|govrun:1|proposal",
            "decisionNodeId": "gov|govrun:1|decision",
            "approvalNodeId": "gov|govrun:1|approval",
        }

        self.service.persist_event_record(observed_event)
        self.service.persist_receipt_record(receipt)
        self.service.upsert_approval_record("approval-1", approval_record)
        self.service.upsert_gateway_approval_record("plugin:approval-1", gateway_record)
        self.service.upsert_workflow_run_record(governance_call_id, workflow_record)
        self.service.upsert_projection_record(governance_call_id, projection_record)
        self.service.upsert_approval_subscription_record(
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

    def test_materialize_debug_snapshot_from_graph_native_record_nodes(self) -> None:
        observed_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        event_ts = "2026-04-03T00:00:00Z"
        governance_call_id = "gov-call-graph-1"
        observed_event["eventId"] = "event-observed-graph-1"
        observed_event["occurredAt"] = event_ts
        observed_event["recordedAt"] = event_ts
        observed_event["subject"] = {"governanceCallId": governance_call_id, "approvalRequestId": None}
        receipt = {
            "receiptId": "receipt-graph-1",
            "receivedAt": event_ts,
            "sourceSystem": "openclaw",
            "sourceEventType": "before_tool_call",
            "adapterVersion": "v1",
            "payloadSha256": "abc",
            "payload": {"sessionId": "approval-demo", "rawEvent": {"toolCallId": "tool-graph-1"}},
            "parseStatus": "accepted",
            "notes": [],
        }
        approval_record = {
            "approvalRequestId": "approval-graph-1",
            "governanceCallId": governance_call_id,
            "decisionId": "decision-graph-1",
            "requestedEventId": "event-approval-graph-1",
            "suspensionId": "suspend-graph-1",
            "status": "pending",
            "requestedAt": event_ts,
            "projection": {"title": "Approval required for exec"},
            "toolCallId": "tool-graph-1",
            "sessionId": observed_event["correlationId"],
            "toolName": "exec",
        }

        self.service.persist_event_record(observed_event)
        self.service.persist_receipt_record(receipt)
        self.service.upsert_approval_record("approval-graph-1", approval_record)

        snapshot = self.service.materialize_debug_snapshot()
        self.assertEqual(snapshot["events"][0]["eventId"], "event-observed-graph-1")
        self.assertEqual(snapshot["receipts"][0]["receiptId"], "receipt-graph-1")
        self.assertEqual(snapshot["approvals"]["approval-graph-1"]["toolName"], "exec")

    def test_canonical_events_persist_as_semantic_graph_nodes_and_edges(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        payload = OpenClawBeforeToolCallPayload.model_validate(raw)
        receipt = build_receipt("before_tool_call", payload)
        observed_event = canonicalize_before_tool_call(payload, receipt).model_dump(mode="json")
        observed_event["eventId"] = "event-observed-semantic-1"
        observed_event["occurredAt"] = "2026-04-03T00:00:00Z"
        observed_event["recordedAt"] = "2026-04-03T00:00:00Z"
        governance_call_id = observed_event["subject"]["governanceCallId"]
        decision_event = {
            "eventId": "event-decision-semantic-1",
            "eventType": "governance.decision_recorded.v1",
            "occurredAt": "2026-04-03T00:00:01Z",
            "recordedAt": "2026-04-03T00:00:01Z",
            "correlationId": observed_event["correlationId"],
            "causationId": observed_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {
                "governanceCallId": governance_call_id,
                "approvalRequestId": None,
            },
            "data": {
                "decisionId": "decision-semantic-1",
                "disposition": "require_approval",
                "reasons": [],
                "policyTrace": [],
                "annotations": {},
            },
        }
        approval_event = {
            "eventId": "event-approval-semantic-1",
            "eventType": "governance.approval_requested.v1",
            "occurredAt": "2026-04-03T00:00:02Z",
            "recordedAt": "2026-04-03T00:00:02Z",
            "correlationId": observed_event["correlationId"],
            "causationId": decision_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {
                "governanceCallId": governance_call_id,
                "approvalRequestId": "approval-semantic-1",
            },
            "data": {
                "approvalRequestId": "approval-semantic-1",
                "decisionId": "decision-semantic-1",
                "title": "Need approval",
                "description": "exec is dangerous",
                "severity": "high",
                "timeoutMs": 60000,
                "timeoutBehavior": "deny",
                "approvalScope": "single_use",
            },
        }

        self.service.persist_event_record(observed_event)
        self.service.persist_event_record(decision_event)
        self.service.persist_event_record(approval_event)

        observed_md = self._node_metadata("govstore|event|event-observed-semantic-1")
        decision_md = self._node_metadata("govstore|event|event-decision-semantic-1")
        approval_md = self._node_metadata("govstore|event|event-approval-semantic-1")
        self.assertEqual(observed_md["entity_type"], "governance_proposal")
        self.assertEqual(decision_md["entity_type"], "governance_decision")
        self.assertEqual(approval_md["entity_type"], "governance_approval_request")

        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-observed-semantic-1->event-decision-semantic-1|governance_decided"
        )
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-decision-semantic-1->event-approval-semantic-1|governance_requires_approval"
        )

        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|event|waiting_approval|govstore|event|event-approval-semantic-1"
        )

    def test_approval_subscription_stays_out_of_conversation_graph(self) -> None:
        self.service.upsert_approval_subscription_record(
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

        got = self.service.conversation_engine.backend.node_get(
            where={"record_kind": "approval_subscription"},
            include=["metadatas"],
        )
        self.assertEqual(got["ids"], [])

        projected = self.service.get_record("approval_subscription", "latest")
        self.assertIsNotNone(projected)
        self.assertEqual(projected["connected"], True)

    def test_backbone_steps_get_scoped_sequence_metadata(self) -> None:
        observed_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        event_ts = "2026-04-03T00:00:00Z"
        governance_call_id = "gov-call-seq-1"
        observed_event["eventId"] = "event-observed-seq-1"
        observed_event["occurredAt"] = event_ts
        observed_event["recordedAt"] = event_ts
        observed_event["subject"] = {"governanceCallId": governance_call_id, "approvalRequestId": None}

        self.service.persist_event_record(observed_event)

        waiting_input = self._node_metadata(f"govbackbone|{governance_call_id}|waiting_input")
        input_received = self._node_metadata(f"govbackbone|{governance_call_id}|input_received")
        proposal = self._node_metadata("govstore|event|event-observed-seq-1")
        self.assertEqual(waiting_input["entity_type"], "governance_backbone_step")
        self.assertEqual(input_received["entity_type"], "governance_backbone_step")
        self.assertEqual(proposal["entity_type"], "governance_proposal")
        self.assertEqual(waiting_input["seq"], 1)
        self.assertEqual(input_received["seq"], 2)
        self.assertEqual(proposal["seq"], 3)
        self.assertEqual(
            self.service.conversation_engine.meta_sqlite.current_scoped_seq(f"governance:{governance_call_id}"),
            3,
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
        self._assert_edge_exists(
            f"govwf|{governance_call_id}|input_received|trigger|{runtime_decision.workflow['runId']}"
        )
        self._assert_edge_exists(
            f"govwf|{governance_call_id}|result|{runtime_decision.workflow['runId']}|policy_rejected"
        )
        self.assertEqual(
            self.service.conversation_engine.meta_sqlite.current_scoped_seq(f"governance:{governance_call_id}"),
            4,
        )

    def test_require_approval_backbone_and_event_chain_stays_connected(self) -> None:
        governance_call_id = "gov-call-chain-1"
        observed_event = load_fixture("canonical", "before_tool_call.require_approval.observed.json")
        observed_event["eventId"] = "event-chain-observed"
        observed_event["occurredAt"] = "2026-04-04T00:00:00Z"
        observed_event["recordedAt"] = "2026-04-04T00:00:00Z"
        observed_event["streamId"] = f"governance/tool-call/{governance_call_id}"
        observed_event["subject"] = {"governanceCallId": governance_call_id, "approvalRequestId": None}
        decision_event = {
            "eventId": "event-chain-decision",
            "eventType": "governance.decision_recorded.v1",
            "occurredAt": "2026-04-04T00:00:01Z",
            "recordedAt": "2026-04-04T00:00:01Z",
            "correlationId": observed_event["correlationId"],
            "causationId": observed_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "decisionId": "decision-chain-1",
                "disposition": "require_approval",
                "reasons": [],
                "policyTrace": [],
                "annotations": {},
            },
        }
        approval_event = {
            "eventId": "event-chain-approval-requested",
            "eventType": "governance.approval_requested.v1",
            "occurredAt": "2026-04-04T00:00:02Z",
            "recordedAt": "2026-04-04T00:00:02Z",
            "correlationId": observed_event["correlationId"],
            "causationId": decision_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {
                "approvalRequestId": "approval-chain-1",
                "decisionId": "decision-chain-1",
                "title": "Need approval",
                "description": "exec is dangerous",
                "severity": "high",
                "timeoutMs": 60000,
                "timeoutBehavior": "deny",
                "approvalScope": "single_use",
            },
        }
        suspended_event = {
            "eventId": "event-chain-suspended",
            "eventType": "governance.execution_suspended.v1",
            "occurredAt": "2026-04-04T00:00:03Z",
            "recordedAt": "2026-04-04T00:00:03Z",
            "correlationId": observed_event["correlationId"],
            "causationId": approval_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {"approvalRequestId": "approval-chain-1", "suspensionId": "suspend-chain-1"},
        }
        resolved_event = {
            "eventId": "event-chain-resolved",
            "eventType": "governance.approval_resolved.v1",
            "occurredAt": "2026-04-04T00:00:04Z",
            "recordedAt": "2026-04-04T00:00:04Z",
            "correlationId": observed_event["correlationId"],
            "causationId": approval_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {"approvalRequestId": "approval-chain-1", "resolution": "allow_once"},
        }
        resumed_event = {
            "eventId": "event-chain-resumed",
            "eventType": "governance.execution_resumed.v1",
            "occurredAt": "2026-04-04T00:00:05Z",
            "recordedAt": "2026-04-04T00:00:05Z",
            "correlationId": observed_event["correlationId"],
            "causationId": resolved_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {"approvalRequestId": "approval-chain-1", "resumeMode": "single_use", "suspensionId": "suspend-chain-1"},
        }
        result_event = {
            "eventId": "event-chain-result",
            "eventType": "governance.result_recorded.v1",
            "occurredAt": "2026-04-04T00:00:05Z",
            "recordedAt": "2026-04-04T00:00:05Z",
            "correlationId": observed_event["correlationId"],
            "causationId": resumed_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {
                "finalDisposition": "allow",
                "resolution": "allow_once",
                "executionOutcome": "not_executed",
                "completionReason": "approval_granted",
            },
        }
        governance_completed_event = {
            "eventId": "event-chain-governance-completed",
            "eventType": "governance.completed.v1",
            "occurredAt": "2026-04-04T00:00:05Z",
            "recordedAt": "2026-04-04T00:00:05Z",
            "correlationId": observed_event["correlationId"],
            "causationId": result_event["eventId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-chain-1"},
            "data": {
                "finalDisposition": "allow",
                "executionOutcome": "not_executed",
                "completionReason": "approval_granted",
            },
        }
        completed_event = {
            "eventId": "event-chain-completed",
            "eventType": "governance.tool_call_completed.v1",
            "occurredAt": "2026-04-04T00:00:06Z",
            "recordedAt": "2026-04-04T00:00:06Z",
            "correlationId": observed_event["correlationId"],
            "streamId": observed_event["streamId"],
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {"outcome": "success", "result": {"exitCode": 0}, "error": None, "durationMs": 42},
        }

        for event in (
            observed_event,
            decision_event,
            approval_event,
            suspended_event,
            resolved_event,
            resumed_event,
            result_event,
            governance_completed_event,
            completed_event,
        ):
            self.service.persist_event_record(event)

        for edge_id in (
            f"govbackbone|{governance_call_id}|edge|require_approval->waiting_approval",
            f"govbackbone|{governance_call_id}|edge|waiting_approval->approval_suspended",
            f"govbackbone|{governance_call_id}|edge|approval_suspended->approval_received",
            f"govbackbone|{governance_call_id}|edge|approval_received->governance_resolved",
            f"govbackbone|{governance_call_id}|edge|governance_resolved->waiting_output",
            f"govbackbone|{governance_call_id}|edge|waiting_output->output_received",
            f"govbackbone|{governance_call_id}|edge|output_received->run_completed",
            f"govevent|{governance_call_id}|edge|event-chain-approval-requested->event-chain-suspended|governance_suspended_for_approval",
            f"govevent|{governance_call_id}|edge|event-chain-suspended->event-chain-resolved|governance_resolved_as",
            f"govevent|{governance_call_id}|edge|event-chain-resolved->event-chain-resumed|governance_resulted_in",
            f"govevent|{governance_call_id}|edge|event-chain-resumed->event-chain-result|governance_result_recorded_as",
            f"govevent|{governance_call_id}|edge|event-chain-result->event-chain-governance-completed|governance_completed",
            f"govevent|{governance_call_id}|edge|event-chain-governance-completed->event-chain-completed|tool_execution_completed_as",
        ):
            self._assert_edge_exists(edge_id)

    def test_receipts_attach_to_semantic_event_nodes(self) -> None:
        raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        payload = OpenClawBeforeToolCallPayload.model_validate(raw)
        receipt = build_receipt("before_tool_call", payload)
        observed_event = canonicalize_before_tool_call(payload, receipt).model_dump(mode="json")
        observed_event["eventId"] = "event-receipt-link-1"
        observed_event["occurredAt"] = "2026-04-04T00:00:00Z"
        observed_event["recordedAt"] = "2026-04-04T00:00:00Z"

        self.service.persist_receipt_record(receipt.model_dump(mode="json"))
        self.service.persist_event_record(observed_event)

        self._assert_edge_exists(
            f"govreceipt|{observed_event['subject']['governanceCallId']}|{receipt.receiptId}|govstore|event|event-receipt-link-1"
        )

    def test_before_and_after_tool_receipts_share_same_governance_scope(self) -> None:
        before_raw = load_fixture("openclaw", "before_tool_call.require_approval.json")
        after_raw = load_fixture("openclaw", "after_tool_call.success.json")
        after_raw["pluginId"] = before_raw["pluginId"]
        after_raw["sessionId"] = before_raw["sessionId"]
        after_raw["toolName"] = before_raw["toolName"]
        after_raw["params"] = dict(before_raw["params"])
        after_raw["rawEvent"]["runId"] = before_raw["rawEvent"]["runId"]
        after_raw["rawEvent"]["toolCallId"] = before_raw["rawEvent"]["toolCallId"]
        after_raw["rawEvent"]["toolName"] = before_raw["toolName"]
        after_raw["rawEvent"]["params"] = dict(before_raw["params"])

        before_payload = OpenClawBeforeToolCallPayload.model_validate(before_raw)
        after_payload = OpenClawAfterToolCallPayload.model_validate(after_raw)

        before_receipt = build_receipt("before_tool_call", before_payload)
        after_receipt = build_receipt("after_tool_call", after_payload)
        observed_event = canonicalize_before_tool_call(before_payload, before_receipt).model_dump(mode="json")
        completed_event = canonicalize_after_tool_call(after_payload, after_receipt).model_dump(mode="json")

        before_scope = self.service._receipt_governance_call_id(before_receipt.model_dump(mode="json"))
        after_scope = self.service._receipt_governance_call_id(after_receipt.model_dump(mode="json"))

        self.assertEqual(before_scope, after_scope)
        self.assertEqual(before_scope, observed_event["subject"]["governanceCallId"])
        self.assertEqual(after_scope, completed_event["subject"]["governanceCallId"])

    def test_approval_pending_after_tool_call_receipt_attaches_to_execution_suspended(self) -> None:
        governance_call_id = stable_governance_call_id(
            [
                "kogwistar-governance",
                "approval-demo",
                "exec",
                "run-approval-pending-1",
                "tool-approval-pending-1",
            ]
        )
        observed_event = {
            "eventId": "event-observed-pending-1",
            "eventType": "governance.tool_call_observed.v1",
            "occurredAt": "2026-04-04T00:00:00Z",
            "recordedAt": "2026-04-04T00:00:00Z",
            "correlationId": "run-approval-pending-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "tool": {"name": "exec", "params": {"command": "echo hello"}},
                "executionContext": {
                    "sessionId": "approval-demo",
                    "runId": "run-approval-pending-1",
                    "toolCallId": "tool-approval-pending-1",
                },
                "sourceRef": {"pluginId": "kogwistar-governance"},
            },
        }
        receipt = {
            "receiptId": "receipt-after-pending-1",
            "receivedAt": "2026-04-04T00:00:03Z",
            "sourceSystem": "openclaw",
            "sourceEventType": "after_tool_call",
            "adapterVersion": "v1",
            "payloadSha256": "pending",
            "payload": {
                "pluginId": "kogwistar-governance",
                "sessionId": "approval-demo",
                "toolName": "exec",
                "rawEvent": {
                    "runId": "run-approval-pending-1",
                    "toolCallId": "tool-approval-pending-1",
                },
                "result": {
                    "details": {
                        "status": "approval-pending",
                        "approvalId": "approval-pending-1",
                    }
                },
            },
            "parseStatus": "accepted",
            "notes": [],
        }
        approval_event = {
            "eventId": "event-approval-pending-1",
            "eventType": "governance.approval_requested.v1",
            "occurredAt": "2026-04-04T00:00:02Z",
            "recordedAt": "2026-04-04T00:00:02Z",
            "correlationId": "run-approval-pending-1",
            "causationId": "event-decision-pending-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-pending-1"},
            "data": {
                "approvalRequestId": "approval-pending-1",
                "decisionId": "decision-pending-1",
                "title": "Need approval",
                "description": "exec is dangerous",
                "severity": "high",
                "timeoutMs": 60000,
                "timeoutBehavior": "deny",
                "approvalScope": "single_use",
            },
        }
        decision_event = {
            "eventId": "event-decision-pending-1",
            "eventType": "governance.decision_recorded.v1",
            "occurredAt": "2026-04-04T00:00:01Z",
            "recordedAt": "2026-04-04T00:00:01Z",
            "correlationId": "run-approval-pending-1",
            "causationId": "event-observed-pending-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "decisionId": "decision-pending-1",
                "disposition": "require_approval",
                "reasons": [],
                "policyTrace": [],
                "annotations": {},
            },
        }
        suspended_event = {
            "eventId": "event-receipt-suspended-1",
            "eventType": "governance.execution_suspended.v1",
            "occurredAt": "2026-04-04T00:00:03Z",
            "recordedAt": "2026-04-04T00:00:03Z",
            "correlationId": "run-approval-pending-1",
            "causationId": "event-approval-pending-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": "approval-pending-1"},
            "data": {
                "approvalRequestId": "approval-pending-1",
                "suspensionId": "suspend-pending-1",
            },
        }

        self.service.persist_receipt_record(receipt)
        self.service.persist_event_record(observed_event)
        self.service.persist_event_record(decision_event)
        self.service.persist_event_record(approval_event)
        self.service.persist_event_record(suspended_event)

        self._assert_edge_exists(
            f"govreceipt|{governance_call_id}|receipt-after-pending-1|govstore|event|event-receipt-suspended-1"
        )

    def test_denial_path_always_appends_resolution_and_denial_edges(self) -> None:
        governance_call_id = "gov-call-denial-chain-1"
        approval_request_id = "approval-denial-chain-1"
        observed_event = {
            "eventId": "event-denial-observed",
            "eventType": "governance.tool_call_observed.v1",
            "occurredAt": "2026-04-04T00:00:00Z",
            "recordedAt": "2026-04-04T00:00:00Z",
            "correlationId": "run-denial-chain-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "tool": {"name": "exec", "params": {"command": "echo hello"}},
                "executionContext": {
                    "sessionId": "approval-demo",
                    "runId": "run-denial-chain-1",
                    "toolCallId": "tool-denial-chain-1",
                },
                "sourceRef": {"pluginId": "kogwistar-governance"},
            },
        }
        decision_event = {
            "eventId": "event-denial-decision",
            "eventType": "governance.decision_recorded.v1",
            "occurredAt": "2026-04-04T00:00:01Z",
            "recordedAt": "2026-04-04T00:00:01Z",
            "correlationId": "run-denial-chain-1",
            "causationId": "event-denial-observed",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "decisionId": "decision-denial-1",
                "disposition": "require_approval",
                "reasons": [],
                "policyTrace": [],
                "annotations": {},
            },
        }
        approval_event = {
            "eventId": "event-denial-approval-requested",
            "eventType": "governance.approval_requested.v1",
            "occurredAt": "2026-04-04T00:00:02Z",
            "recordedAt": "2026-04-04T00:00:02Z",
            "correlationId": "run-denial-chain-1",
            "causationId": "event-denial-decision",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "approvalRequestId": approval_request_id,
                "decisionId": "decision-denial-1",
                "title": "Need approval",
                "description": "exec is dangerous",
                "severity": "high",
                "timeoutMs": 60000,
                "timeoutBehavior": "deny",
                "approvalScope": "single_use",
            },
        }
        suspended_event = {
            "eventId": "event-denial-suspended",
            "eventType": "governance.execution_suspended.v1",
            "occurredAt": "2026-04-04T00:00:03Z",
            "recordedAt": "2026-04-04T00:00:03Z",
            "correlationId": "run-denial-chain-1",
            "causationId": approval_event["eventId"],
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "approvalRequestId": approval_request_id,
                "suspensionId": "suspend-denial-1",
            },
        }
        resolved_event = {
            "eventId": "event-denial-resolved",
            "eventType": "governance.approval_resolved.v1",
            "occurredAt": "2026-04-04T00:00:04Z",
            "recordedAt": "2026-04-04T00:00:04Z",
            "correlationId": "run-denial-chain-1",
            "causationId": approval_event["eventId"],
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "approvalRequestId": approval_request_id,
                "resolution": "deny",
            },
        }
        denied_event = {
            "eventId": "event-denial-result",
            "eventType": "governance.execution_denied.v1",
            "occurredAt": "2026-04-04T00:00:05Z",
            "recordedAt": "2026-04-04T00:00:05Z",
            "correlationId": "run-denial-chain-1",
            "causationId": resolved_event["eventId"],
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "approvalRequestId": approval_request_id,
                "suspensionId": "suspend-denial-1",
                "denyReason": "approval_denied",
            },
        }
        result_event = {
            "eventId": "event-denial-governance-result",
            "eventType": "governance.result_recorded.v1",
            "occurredAt": "2026-04-04T00:00:06Z",
            "recordedAt": "2026-04-04T00:00:06Z",
            "correlationId": "run-denial-chain-1",
            "causationId": denied_event["eventId"],
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "finalDisposition": "deny",
                "resolution": "deny",
                "executionOutcome": "not_executed",
                "completionReason": "approval_denied",
            },
        }
        completed_event = {
            "eventId": "event-denial-completed",
            "eventType": "governance.completed.v1",
            "occurredAt": "2026-04-04T00:00:07Z",
            "recordedAt": "2026-04-04T00:00:07Z",
            "correlationId": "run-denial-chain-1",
            "causationId": result_event["eventId"],
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": approval_request_id},
            "data": {
                "finalDisposition": "deny",
                "executionOutcome": "not_executed",
                "completionReason": "approval_denied",
            },
        }

        for event in (
            observed_event,
            decision_event,
            approval_event,
            suspended_event,
            resolved_event,
            denied_event,
            result_event,
            completed_event,
        ):
            self.service.persist_event_record(event)

        self._node_metadata("govstore|event|event-denial-resolved")
        self._node_metadata("govstore|event|event-denial-result")
        self._node_metadata("govstore|event|event-denial-governance-result")
        self._node_metadata("govstore|event|event-denial-completed")
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-denial-suspended->event-denial-resolved|governance_resolved_as"
        )
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-denial-resolved->event-denial-result|governance_resulted_in"
        )
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-denial-result->event-denial-governance-result|governance_result_recorded_as"
        )
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-denial-governance-result->event-denial-completed|governance_completed"
        )
        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|edge|approval_suspended->approval_received"
        )
        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|edge|approval_received->governance_resolved"
        )
        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|edge|governance_resolved->run_completed"
        )

    def test_policy_block_path_appends_result_and_completed_edges(self) -> None:
        governance_call_id = "gov-call-policy-block-1"
        observed_event = {
            "eventId": "event-policy-block-observed",
            "eventType": "governance.tool_call_observed.v1",
            "occurredAt": "2026-04-04T00:00:00Z",
            "recordedAt": "2026-04-04T00:00:00Z",
            "correlationId": "run-policy-block-1",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "tool": {"name": "exec", "params": {"command": "rm -rf /tmp/x"}},
                "executionContext": {
                    "sessionId": "approval-demo",
                    "runId": "run-policy-block-1",
                    "toolCallId": "tool-policy-block-1",
                },
                "sourceRef": {"pluginId": "kogwistar-governance"},
            },
        }
        decision_event = {
            "eventId": "event-policy-block-decision",
            "eventType": "governance.decision_recorded.v1",
            "occurredAt": "2026-04-04T00:00:01Z",
            "recordedAt": "2026-04-04T00:00:01Z",
            "correlationId": "run-policy-block-1",
            "causationId": "event-policy-block-observed",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "decisionId": "decision-policy-block-1",
                "disposition": "block",
                "reasons": [],
                "policyTrace": [],
                "annotations": {},
            },
        }
        result_event = {
            "eventId": "event-policy-block-result",
            "eventType": "governance.result_recorded.v1",
            "occurredAt": "2026-04-04T00:00:02Z",
            "recordedAt": "2026-04-04T00:00:02Z",
            "correlationId": "run-policy-block-1",
            "causationId": "event-policy-block-decision",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "finalDisposition": "block",
                "executionOutcome": "not_executed",
                "completionReason": "policy_blocked",
            },
        }
        completed_event = {
            "eventId": "event-policy-block-completed",
            "eventType": "governance.completed.v1",
            "occurredAt": "2026-04-04T00:00:03Z",
            "recordedAt": "2026-04-04T00:00:03Z",
            "correlationId": "run-policy-block-1",
            "causationId": "event-policy-block-result",
            "streamId": f"governance/tool-call/{governance_call_id}",
            "subject": {"governanceCallId": governance_call_id, "approvalRequestId": None},
            "data": {
                "finalDisposition": "block",
                "executionOutcome": "not_executed",
                "completionReason": "policy_blocked",
            },
        }

        for event in (observed_event, decision_event, result_event, completed_event):
            self.service.persist_event_record(event)

        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-policy-block-decision->event-policy-block-result|governance_result_recorded_as"
        )
        self._assert_edge_exists(
            f"govevent|{governance_call_id}|edge|event-policy-block-result->event-policy-block-completed|governance_completed"
        )
        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|edge|policy_rejected->governance_resolved"
        )
        self._assert_edge_exists(
            f"govbackbone|{governance_call_id}|edge|governance_resolved->run_completed"
        )

    def _node_metadata(self, node_id: str) -> dict:
        got = self.service.conversation_engine.backend.node_get(ids=[node_id], include=["metadatas"])
        self.assertTrue(got["ids"], f"missing node {node_id}")
        metadatas = got.get("metadatas") or []
        self.assertTrue(metadatas, f"missing metadata for node {node_id}")
        metadata = metadatas[0]
        self.assertIsInstance(metadata, dict)
        return metadata

    def _edge_metadata(self, edge_id: str) -> dict:
        got = self.service.conversation_engine.backend.edge_get(ids=[edge_id], include=["metadatas"])
        self.assertTrue(got["ids"], f"missing edge {edge_id}")
        metadatas = got.get("metadatas") or []
        self.assertTrue(metadatas, f"missing metadata for edge {edge_id}")
        metadata = metadatas[0]
        self.assertIsInstance(metadata, dict)
        return metadata

    def _assert_edge_exists(self, edge_id: str) -> None:
        got = self.service.conversation_engine.backend.edge_get(ids=[edge_id], include=[])
        self.assertTrue(got["ids"], f"missing edge {edge_id}")
