import test from "node:test";
import assert from "node:assert/strict";

import {
  normalizeBeforeToolHook,
  normalizeAfterToolHook,
  normalizeApprovalResolution,
  toWirePayload,
  toDebugView,
  toAfterCallWirePayload,
  toAfterCallDebugView,
  toApprovalWire,
  decisionToHookResult,
  structuralSummary,
} from "../dist/governance-contract.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCtx(overrides = {}) {
  return {
    toolName: "exec",
    sessionId: "sess-1",
    sessionKey: "sess-1",
    agentId: "agent-main",
    runId: "run-1",
    toolCallId: "call-1",
    ...overrides,
  };
}

function makeBeforeEvent(overrides = {}) {
  return {
    toolName: "exec",
    params: { command: "echo hello" },
    runId: "run-1",
    toolCallId: "call-1",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// structuralSummary
// ---------------------------------------------------------------------------

test("structuralSummary produces shape-level signal", () => {
  assert.equal(structuralSummary({ a: 1, b: 2, c: 3 }), "[object: 3 keys]");
  assert.equal(structuralSummary([1, 2, 3, 4]), "[array: 4 items]");
  assert.equal(structuralSummary("hello world"), "[string: 11 chars]");
  assert.equal(structuralSummary(42), "[number]");
  assert.equal(structuralSummary(true), "[boolean]");
  assert.equal(structuralSummary(null), "[null]");
  assert.equal(structuralSummary(undefined), "[undefined]");
});

// ---------------------------------------------------------------------------
// Identity invariants
// ---------------------------------------------------------------------------

test("governanceCallId carries toolCallId from ctx — not fabricated", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ toolCallId: "call-abc" }),
    makeCtx({ toolCallId: "call-abc" }),
    "kogwistar-governance"
  );
  assert.equal(normalized.governanceCallId, "call-abc");
});

test("normalizeBeforeToolHook throws when toolCallId is absent — never silently proceeds", () => {
  assert.throws(
    () =>
      normalizeBeforeToolHook(
        makeBeforeEvent({ toolCallId: undefined }),
        makeCtx({ toolCallId: undefined }),
        "kogwistar-governance"
      ),
    (err) => {
      assert.ok(err instanceof Error);
      assert.ok(
        err.message.includes("ctx.toolCallId is absent"),
        `Expected message about absent ctx.toolCallId, got: ${err.message}`
      );
      return true;
    }
  );
});

test("normalizeAfterToolHook throws when toolCallId is absent — same invariant", () => {
  assert.throws(
    () =>
      normalizeAfterToolHook(
        makeBeforeEvent({ toolCallId: undefined }),
        makeCtx({ toolCallId: undefined }),
        "kogwistar-governance"
      ),
    (err) => {
      assert.ok(err instanceof Error);
      assert.ok(
        err.message.includes("ctx.toolCallId is absent"),
        `Expected message about absent ctx.toolCallId, got: ${err.message}`
      );
      return true;
    }
  );
});

test("localObservationId is distinct from governanceCallId", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ toolCallId: "call-xyz" }),
    makeCtx({ toolCallId: "call-xyz" }),
    "kogwistar-governance"
  );
  assert.notEqual(normalized.localObservationId, normalized.governanceCallId);
  assert.ok(typeof normalized.localObservationId === "string");
  assert.ok(normalized.localObservationId.startsWith("obs-"));
});

test("localObservationId increments per normalization call", () => {
  const a = normalizeBeforeToolHook(makeBeforeEvent(), makeCtx(), "gov");
  const b = normalizeBeforeToolHook(makeBeforeEvent(), makeCtx(), "gov");
  assert.notEqual(a.localObservationId, b.localObservationId);
});

test("gatewayApprovalId and governanceCallId are separate identities in approval resolution", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ toolCallId: "call-1" }),
    makeCtx({ toolCallId: "call-1" }),
    "kogwistar-governance"
  );
  const resolution = normalizeApprovalResolution({
    normalized,
    resolution: "allow-once",
    approvalId: "gateway-approval-999",
  });

  assert.equal(resolution.governanceCallId, "call-1");
  assert.equal(resolution.approvalId, "gateway-approval-999");
  // They must never be equal to each other (different identity domains)
  assert.notEqual(resolution.governanceCallId, resolution.approvalId);
});

test("approvalId accepts null when bridge returns no approval id", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const resolution = normalizeApprovalResolution({
    normalized,
    resolution: "deny",
    approvalId: null,
  });
  assert.equal(resolution.approvalId, null);
});

// ---------------------------------------------------------------------------
// Wire payload shape
// ---------------------------------------------------------------------------

test("wire payload does not contain rawEvent", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal("rawEvent" in wire, false);
});

test("wire payload does not contain localObservationId", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal("localObservationId" in wire, false);
});

test("wire payload does not contain paramsSummary", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal("paramsSummary" in wire, false);
});

test("wire payload contains params", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ params: { cmd: "ls" } }),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.deepEqual(wire.params, { cmd: "ls" });
});

test("wire payload preserves nullable sessionId", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    { toolName: "exec", toolCallId: "call-no-session" }, // no sessionId or sessionKey
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal(wire.sessionId, null);
});

test("wire payload toolName: falls back to ctx.toolName when absent in event", () => {
  // event has no toolName — falls back to ctx.toolName
  const normalized = normalizeBeforeToolHook(
    { params: { x: 1 } },
    makeCtx({ toolName: "exec" }),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal(wire.toolName, "exec");
});

test("wire payload toolName: null when absent in both event and ctx", () => {
  // Neither event nor ctx provides toolName
  const normalized = normalizeBeforeToolHook(
    { params: {} },
    { sessionId: "s-no-tool", toolCallId: "call-no-tool" }, // no toolName
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal(wire.toolName, null);
});

// ---------------------------------------------------------------------------
// Debug view shape
// ---------------------------------------------------------------------------

test("debug view does not contain params (raw value)", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ params: { secret: "password123" } }),
    makeCtx(),
    "kogwistar-governance"
  );
  const debug = toDebugView(normalized);
  assert.equal("params" in debug, false);
});

test("debug view contains paramsSummary instead of params", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ params: { a: 1, b: 2, c: 3, d: 4 } }),
    makeCtx(),
    "kogwistar-governance"
  );
  const debug = toDebugView(normalized);
  assert.equal(debug.paramsSummary, "[object: 4 keys]");
});

test("debug view contains localObservationId", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const debug = toDebugView(normalized);
  assert.ok(typeof debug.localObservationId === "string");
  assert.ok(debug.localObservationId.startsWith("obs-"));
});

// ---------------------------------------------------------------------------
// Wire ≠ debug (projection independence)
// ---------------------------------------------------------------------------

test("wire and debug projections are structurally different objects", () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent(),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  const debug = toDebugView(normalized);

  // Different key sets
  assert.equal("params" in wire, true);
  assert.equal("params" in debug, false);
  assert.equal("paramsSummary" in wire, false);
  assert.equal("paramsSummary" in debug, true);
  assert.equal("localObservationId" in wire, false);
  assert.equal("localObservationId" in debug, true);

  // They are not reference-equal
  assert.notEqual(wire, debug);
});

// ---------------------------------------------------------------------------
// After-tool-call: ambiguity preservation
// ---------------------------------------------------------------------------

test("after-tool-call with result: present preserves result in wire", () => {
  const normalized = normalizeAfterToolHook(
    makeBeforeEvent({ result: { exitCode: 0 } }),
    makeCtx(),
    "kogwistar-governance"
  );
  const wire = toAfterCallWirePayload(normalized);
  assert.deepEqual(wire.result, { exitCode: 0 });
});

test("after-tool-call with result absent keeps result absent — not null", () => {
  const event = { toolName: "exec", params: { command: "echo" } }; // no result key
  const normalized = normalizeAfterToolHook(event, makeCtx(), "kogwistar-governance");

  // result absent in event → undefined in normalized, absent from wire
  assert.equal(normalized.result, undefined);
  const wire = toAfterCallWirePayload(normalized);
  assert.equal("result" in wire, false);
});

test("after-tool-call with error absent keeps error absent — not empty string", () => {
  const event = { toolName: "exec", params: {} }; // no error key
  const normalized = normalizeAfterToolHook(event, makeCtx(), "kogwistar-governance");
  assert.equal(normalized.error, undefined);
});

test("after-tool-call debug view contains resultSummary when result present", () => {
  const normalized = normalizeAfterToolHook(
    makeBeforeEvent({ result: [1, 2, 3] }),
    makeCtx(),
    "kogwistar-governance"
  );
  const debug = toAfterCallDebugView(normalized);
  assert.equal(debug.resultSummary, "[array: 3 items]");
  assert.equal("result" in debug, false);
});

test("after-tool-call debug view has no resultSummary when result not reported", () => {
  const event = { toolName: "exec", params: {} };
  const normalized = normalizeAfterToolHook(event, makeCtx(), "kogwistar-governance");
  const debug = toAfterCallDebugView(normalized);
  assert.equal("resultSummary" in debug, false);
});

// ---------------------------------------------------------------------------
// decisionToHookResult
// ---------------------------------------------------------------------------

test("decisionToHookResult: allow → empty object", () => {
  const result = decisionToHookResult({
    decision: { decision: "allow" },
    onResolution: async () => {},
  });
  assert.deepEqual(result, {});
});

test("decisionToHookResult: block → block shape", () => {
  const result = decisionToHookResult({
    decision: { decision: "block", reason: "dangerous command" },
    onResolution: async () => {},
  });
  assert.deepEqual(result, { block: true, blockReason: "dangerous command" });
});

test("decisionToHookResult: requireApproval applies defaults", () => {
  const result = decisionToHookResult({
    decision: {
      decision: "requireApproval",
      title: "Risky op",
      description: "Approve?",
      approvalId: "gw-approval-1",
    },
    defaultSeverity: "critical",
    onResolution: async () => {},
  });
  assert.equal(result.requireApproval?.severity, "critical");
  assert.equal(result.requireApproval?.timeoutMs, 120000);
  assert.equal(result.requireApproval?.timeoutBehavior, "deny");
});

test("approval resolution carries governanceCallId and separate gatewayApprovalId", async () => {
  const normalized = normalizeBeforeToolHook(
    makeBeforeEvent({ toolCallId: "attempt-77" }),
    makeCtx({ toolCallId: "attempt-77" }),
    "kogwistar-governance"
  );

  const captured = [];
  const result = decisionToHookResult({
    decision: {
      decision: "requireApproval",
      title: "T",
      description: "D",
      approvalId: "gw-approval-42",
    },
    onResolution: async (resolution) => {
      captured.push(
        toApprovalWire(
          normalizeApprovalResolution({
            normalized,
            resolution,
            approvalId: "gw-approval-42",
          })
        )
      );
    },
  });

  await result.requireApproval.onResolution("allow-once");

  assert.equal(captured.length, 1);
  const wire = captured[0];

  // Identity invariant: these must never be equal
  assert.equal(wire.governanceCallId, undefined); // governanceCallId NOT on wire
  assert.equal(wire.approvalId, "gw-approval-42");  // approvalId IS on wire (matches bridge DTO)

  // Wire shape: no governanceCallId, no localObservationId
  assert.equal("governanceCallId" in wire, false);
  assert.equal("localObservationId" in wire, false);
});
