#!/usr/bin/env node

/**
 * Manual live smoke test for the OpenClaw governance bridge.
 *
 * Run this when you want a human-readable proof trail with:
 * - bridge startup logs
 * - plugin debug payload logs
 * - before_tool_call / after_tool_call / approval resolution round-trips
 * - final bridge state printed as JSON
 *
 * Usage:
 *   node scripts/manual-governance-smoke.mjs
 *   node scripts/manual-governance-smoke.mjs --use-existing-bridge --bridge-url http://127.0.0.1:8788
 *
 * Keep this script if you want a one-command inspection tool. Discard it only
 * if you do not want a manual verification path alongside the automated test.
 */
import {
  fetchBridgeState,
  loadPluginHandlers,
  serializeHookResult,
  startBridge,
  waitForBridge,
} from "./lib/openclaw-governance-harness.mjs";

function parseArgs(argv) {
  const options = {
    bridgeUrl: "http://127.0.0.1:8788",
    useExistingBridge: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--use-existing-bridge") {
      options.useExistingBridge = true;
      continue;
    }
    if (token === "--bridge-url") {
      const value = argv[index + 1];
      if (!value) {
        throw new Error("--bridge-url requires a value");
      }
      options.bridgeUrl = value;
      index += 1;
      continue;
    }
    throw new Error(`unknown argument: ${token}`);
  }

  return options;
}

function printScenarioHeader(name) {
  console.log(`\n=== ${name} ===`);
}

function printNewBridgeState(previousState, nextState) {
  const newEvents = nextState.events.slice(previousState.events.length);
  const newApprovals = Object.entries(nextState.approvals).filter(
    ([approvalId, approval]) =>
      !previousState.approvals[approvalId] ||
      JSON.stringify(previousState.approvals[approvalId]) !== JSON.stringify(approval)
  );

  console.log("New bridge events:");
  for (const event of newEvents) {
    console.log(`- ${event.eventType}`);
  }
  if (newEvents.length === 0) {
    console.log("- none");
  }

  console.log("Approval state changes:");
  for (const [approvalId, approval] of newApprovals) {
    console.log(`- ${approvalId}: ${approval.status}`);
  }
  if (newApprovals.length === 0) {
    console.log("- none");
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  let bridge = null;

  if (options.useExistingBridge) {
    await waitForBridge(options.bridgeUrl);
    console.log(`Using existing bridge at ${options.bridgeUrl}`);
  } else {
    bridge = await startBridge({ streamOutput: true });
    options.bridgeUrl = bridge.bridgeUrl;
    console.log(`Started local bridge at ${options.bridgeUrl}`);
  }

  try {
    const plugin = await loadPluginHandlers({
      bridgeUrl: options.bridgeUrl,
      logPayloads: true,
    });

    let state = await fetchBridgeState(options.bridgeUrl);

    printScenarioHeader("ALLOW");
    const allowEvent = {
      toolName: "read",
      params: { path: "/tmp/demo.txt" },
      runId: "run-allow",
      toolCallId: "call-allow",
    };
    const allowCtx = {
      toolName: "read",
      sessionId: "sess-allow",
      sessionKey: "sess-allow",
      agentId: "agent-main",
      runId: "run-allow",
      toolCallId: "call-allow",
    };
    const allowDecision = await plugin.beforeToolCall(allowEvent, allowCtx);
    console.log("before_tool_call result:", serializeHookResult(allowDecision));
    await plugin.afterToolCall({ ...allowEvent, result: { content: "ok" } }, allowCtx);
    let nextState = await fetchBridgeState(options.bridgeUrl);
    printNewBridgeState(state, nextState);
    state = nextState;

    printScenarioHeader("BLOCK");
    const blockDecision = await plugin.beforeToolCall(
      {
        toolName: "exec",
        params: { command: "rm -rf /tmp/demo" },
        runId: "run-block",
        toolCallId: "call-block",
      },
      {
        toolName: "exec",
        sessionId: "sess-block",
        sessionKey: "sess-block",
        agentId: "agent-main",
        runId: "run-block",
        toolCallId: "call-block",
      }
    );
    console.log("before_tool_call result:", serializeHookResult(blockDecision));
    nextState = await fetchBridgeState(options.bridgeUrl);
    printNewBridgeState(state, nextState);
    state = nextState;

    printScenarioHeader("REQUIRE APPROVAL -> allow-once");
    const approvalEvent = {
      toolName: "exec",
      params: { command: "echo hello" },
      runId: "run-approval",
      toolCallId: "call-approval",
    };
    const approvalCtx = {
      toolName: "exec",
      sessionId: "sess-approval",
      sessionKey: "sess-approval",
      agentId: "agent-main",
      runId: "run-approval",
      toolCallId: "call-approval",
    };
    const approvalDecision = await plugin.beforeToolCall(approvalEvent, approvalCtx);
    console.log("before_tool_call result:", serializeHookResult(approvalDecision));
    await approvalDecision.requireApproval.onResolution("allow-once");
    await plugin.afterToolCall(
      { ...approvalEvent, result: { exitCode: 0, stdout: "hello" } },
      approvalCtx
    );
    nextState = await fetchBridgeState(options.bridgeUrl);
    printNewBridgeState(state, nextState);
    state = nextState;

    printScenarioHeader("REQUIRE APPROVAL -> deny");
    const denyDecision = await plugin.beforeToolCall(
      {
        toolName: "exec",
        params: { command: "echo hello" },
        runId: "run-deny",
        toolCallId: "call-deny",
      },
      {
        toolName: "exec",
        sessionId: "sess-deny",
        sessionKey: "sess-deny",
        agentId: "agent-main",
        runId: "run-deny",
        toolCallId: "call-deny",
      }
    );
    console.log("before_tool_call result:", serializeHookResult(denyDecision));
    await denyDecision.requireApproval.onResolution("deny");
    nextState = await fetchBridgeState(options.bridgeUrl);
    printNewBridgeState(state, nextState);

    console.log("\nPlugin debug logs:");
    for (const entry of plugin.logs) {
      console.log(`- ${entry.level}: ${entry.message}`);
    }

    console.log("\nFinal bridge state:");
    console.log(JSON.stringify(nextState, null, 2));
  } finally {
    if (bridge) {
      await bridge.stop();
    }
  }
}

main().catch((error) => {
  console.error(String(error.stack || error));
  process.exit(1);
});
