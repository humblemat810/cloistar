import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAfterToolCallPayload,
  buildApprovalResolutionPayload,
  buildBeforeToolCallPayload,
  decisionToHookResult,
} from "../dist/governance-contract.js";

test("buildBeforeToolCallPayload extracts plugin and event fields", () => {
  const event = {
    toolName: "exec",
    params: { command: "rm -rf /" },
  };
  const ctx = {
    sessionId: "sess-1",
    toolName: "exec",
  };

  assert.deepEqual(buildBeforeToolCallPayload("kogwistar-governance", event, ctx), {
    pluginId: "kogwistar-governance",
    sessionId: "sess-1",
    toolName: "exec",
    params: { command: "rm -rf /" },
    rawEvent: event,
  });
});

test("buildAfterToolCallPayload captures result payloads", () => {
  const event = {
    toolName: "exec",
    params: { command: "echo ok" },
    result: { exitCode: 0 },
  };
  const ctx = {
    sessionId: "sess-2",
    toolName: "exec",
  };

  assert.deepEqual(buildAfterToolCallPayload("kogwistar-governance", event, ctx), {
    pluginId: "kogwistar-governance",
    sessionId: "sess-2",
    toolName: "exec",
    params: { command: "echo ok" },
    result: { exitCode: 0 },
    rawEvent: event,
  });
});

test("decisionToHookResult maps block decisions to hook blocks", async () => {
  const result = decisionToHookResult({
    decision: { decision: "block", reason: "dangerous command" },
    onResolution: async () => {},
  });

  assert.deepEqual(result, {
    block: true,
    blockReason: "dangerous command",
  });
});

test("decisionToHookResult maps approval decisions and emits approval resolution payloads", async () => {
  const event = {
    toolName: "exec",
    params: {},
  };
  const ctx = {
    sessionId: "sess-3",
    toolName: "exec",
  };
  const calls = [];

  const result = decisionToHookResult({
    decision: {
      decision: "requireApproval",
      title: "Approval required",
      description: "Dangerous command",
      approvalId: "approval-1",
    },
    defaultSeverity: "critical",
    onResolution: async (resolution) => {
      calls.push(
        buildApprovalResolutionPayload({
          pluginId: "kogwistar-governance",
          event,
          ctx,
          resolution,
          approvalId: "approval-1",
        })
      );
    },
  });

  assert.equal(typeof result.requireApproval.onResolution, "function");
  assert.equal(result.requireApproval.severity, "critical");
  assert.equal(result.requireApproval.timeoutBehavior, "deny");

  await result.requireApproval.onResolution("allow-once");

  assert.deepEqual(calls, [
    {
      pluginId: "kogwistar-governance",
      sessionId: "sess-3",
      toolName: "exec",
      resolution: "allow-once",
      approvalId: "approval-1",
      rawEvent: event,
    },
  ]);
});
