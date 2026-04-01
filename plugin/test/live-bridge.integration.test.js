import test from "node:test";
import assert from "node:assert/strict";

/**
 * Live integration test for the governance adapter.
 *
 * This test is worth keeping because it proves the local plugin and bridge can
 * round-trip real HTTP payloads against a live bridge process, which unit tests
 * alone cannot guarantee.
 */
import {
  fetchBridgeState,
  loadPluginHandlers,
  startBridge,
} from "../../scripts/lib/openclaw-governance-harness.mjs";

function makeContext(toolName, sessionId, overrides = {}) {
  return {
    toolName,
    sessionId,
    sessionKey: sessionId,
    agentId: "agent-main",
    runId: `run-${sessionId}`,
    toolCallId: `call-${sessionId}`,
    ...overrides,
  };
}

test("plugin and bridge allow a safe tool call and record completion", async () => {
  const bridge = await startBridge();
  try {
    const plugin = await loadPluginHandlers({ bridgeUrl: bridge.bridgeUrl });
    assert.equal(typeof plugin.beforeToolCall, "function");
    assert.equal(typeof plugin.afterToolCall, "function");

    const event = {
      toolName: "read",
      params: { path: "/tmp/demo.txt" },
      runId: "run-allow",
      toolCallId: "call-allow",
    };
    const ctx = makeContext("read", "sess-allow", {
      runId: "run-allow",
      toolCallId: "call-allow",
    });

    const decision = await plugin.beforeToolCall(event, ctx);
    assert.deepEqual(decision, {});

    await plugin.afterToolCall(
      {
        ...event,
        result: { content: "ok" },
      },
      ctx
    );

    const state = await fetchBridgeState(bridge.bridgeUrl);
    assert.deepEqual(
      state.events.map((entry) => entry.eventType),
      [
        "governance.tool_call_observed.v1",
        "governance.decision_recorded.v1",
        "governance.tool_call_completed.v1",
      ]
    );
    assert.equal(state.events[1].data.disposition, "allow");
    assert.equal(state.events[2].data.outcome, "success");
    assert.equal(state.receipts.length, 2);
  } finally {
    await bridge.stop();
  }
});

test("plugin and bridge block dangerous commands", async () => {
  const bridge = await startBridge();
  try {
    const plugin = await loadPluginHandlers({ bridgeUrl: bridge.bridgeUrl });

    const decision = await plugin.beforeToolCall(
      {
        toolName: "exec",
        params: { command: "rm -rf /tmp/demo" },
        runId: "run-block",
        toolCallId: "call-block",
      },
      makeContext("exec", "sess-block", {
        runId: "run-block",
        toolCallId: "call-block",
      })
    );

    assert.deepEqual(decision, {
      block: true,
      blockReason: "Blocked by policy marker: rm -rf",
    });

    const state = await fetchBridgeState(bridge.bridgeUrl);
    assert.deepEqual(
      state.events.map((entry) => entry.eventType),
      ["governance.tool_call_observed.v1", "governance.decision_recorded.v1"]
    );
    assert.equal(state.events[1].data.disposition, "block");
    assert.deepEqual(state.approvals, {});
  } finally {
    await bridge.stop();
  }
});

test("plugin and bridge round-trip approval resolution with real OpenClaw resolution values", async () => {
  const bridge = await startBridge();
  try {
    const plugin = await loadPluginHandlers({ bridgeUrl: bridge.bridgeUrl });
    const event = {
      toolName: "exec",
      params: { command: "echo hello" },
      runId: "run-approval",
      toolCallId: "call-approval",
    };
    const ctx = makeContext("exec", "sess-approval", {
      runId: "run-approval",
      toolCallId: "call-approval",
    });

    const decision = await plugin.beforeToolCall(event, ctx);
    assert.equal(typeof decision.requireApproval?.onResolution, "function");
    assert.equal(decision.requireApproval?.title, "Approval required for exec");
    assert.equal(decision.requireApproval?.timeoutBehavior, "deny");

    let state = await fetchBridgeState(bridge.bridgeUrl);
    const approvalId = Object.keys(state.approvals)[0];
    assert.ok(approvalId);
    assert.equal(state.approvals[approvalId].status, "pending");
    assert.deepEqual(
      state.events.map((entry) => entry.eventType),
      [
        "governance.tool_call_observed.v1",
        "governance.decision_recorded.v1",
        "governance.approval_requested.v1",
        "governance.execution_suspended.v1",
      ]
    );

    await decision.requireApproval.onResolution("allow-once");

    await plugin.afterToolCall(
      {
        ...event,
        result: { exitCode: 0, stdout: "hello" },
      },
      ctx
    );

    state = await fetchBridgeState(bridge.bridgeUrl);
    assert.equal(state.approvals[approvalId].status, "allow_once");
    assert.deepEqual(
      state.events.map((entry) => entry.eventType),
      [
        "governance.tool_call_observed.v1",
        "governance.decision_recorded.v1",
        "governance.approval_requested.v1",
        "governance.execution_suspended.v1",
        "governance.approval_resolved.v1",
        "governance.execution_resumed.v1",
        "governance.tool_call_completed.v1",
      ]
    );
    assert.equal(state.events[4].data.approvalRequestId, approvalId);
    assert.equal(state.events[4].data.resolution, "allow_once");
    assert.equal(state.events[5].data.resumeMode, "single_use");
  } finally {
    await bridge.stop();
  }
});

test("plugin and bridge record deny approval resolutions", async () => {
  const bridge = await startBridge();
  try {
    const plugin = await loadPluginHandlers({ bridgeUrl: bridge.bridgeUrl });
    const decision = await plugin.beforeToolCall(
      {
        toolName: "exec",
        params: { command: "echo hello" },
        runId: "run-deny",
        toolCallId: "call-deny",
      },
      makeContext("exec", "sess-deny", {
        runId: "run-deny",
        toolCallId: "call-deny",
      })
    );

    await decision.requireApproval.onResolution("deny");

    const state = await fetchBridgeState(bridge.bridgeUrl);
    const approvalId = Object.keys(state.approvals)[0];
    assert.equal(state.approvals[approvalId].status, "deny");
    assert.deepEqual(
      state.events.map((entry) => entry.eventType),
      [
        "governance.tool_call_observed.v1",
        "governance.decision_recorded.v1",
        "governance.approval_requested.v1",
        "governance.execution_suspended.v1",
        "governance.approval_resolved.v1",
        "governance.execution_denied.v1",
      ]
    );
    assert.equal(state.events[4].data.resolution, "deny");
    assert.equal(state.events[5].data.denyReason, "approval_denied");
  } finally {
    await bridge.stop();
  }
});
