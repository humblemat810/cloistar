# Testing — `plugin-governance`

This guide explains the test architecture, how to run each tier, and how to add or debug tests.

---

## Test tiers

The plugin uses two separate test files with different execution characteristics:

| Script | File | Speed | Requires bridge | When to run |
|---|---|---|---|---|
| `npm test` | `governance-contract.test.js` | ~1 s | ✗ | Always — CI, pre-commit |
| `npm run test:integration` | `live-bridge.integration.test.js` | ~4 min | ✓ | Before merging, on full dev cycle |
| `npm run test:all` | Both files | ~4 min | ✓ | Release validation |

> **TL;DR — CI:** run `npm test`. **Full local check:** run `npm run test:all`.

---

## Contract tests (`governance-contract.test.js`)

These tests run entirely in-process with no network calls. They validate the plugin's
pure-TypeScript layer — schema contracts, normalization invariants, and projection rules.

```bash
cd plugin-governance
npm test
# → 28 passing in ~1 s
```

### What they prove

- `governanceCallId` always comes from `ctx.toolCallId` — never fabricated
- `localObservationId` is distinct from `governanceCallId`
- Wire payload **excludes** `rawEvent`, `localObservationId`, `paramsSummary`
- Wire payload **includes** `params` (not a summary)
- Debug view **includes** `paramsSummary` and **excludes** raw `params`
- `approvalId` and `governanceCallId` are separate identities in resolution
- `decisionToHookResult` maps `allow → {}`, `block → { block, blockReason }`, `requireApproval → { requireApproval: { ... } }`

### Adding a new contract test

```js
// test/governance-contract.test.js
test("my invariant", () => {
  const normalized = normalizeBeforeToolHook(
    { toolName: "read", params: {} },
    { toolCallId: "call-1", sessionId: "s", agentId: "a", runId: "r" },
    "kogwistar-governance"
  );
  const wire = toWirePayload(normalized);
  assert.equal(wire.toolName, "read");
  assert.ok(!("governanceCallId" in wire)); // never on wire
});
```

---

## Integration tests (`live-bridge.integration.test.js`)

These tests spawn the real Python bridge process and send real HTTP requests through the
full plugin → bridge stack. Each test:

1. Spawns a fresh bridge on a free port
2. Waits for `/debug/state` to return 200 (readiness probe — see below)
3. Exercises a complete governance flow
4. Asserts on both the plugin's decision result **and** the bridge's canonical event log
5. Stops the bridge (SIGTERM, SIGKILL fallback after 5 s)

```bash
cd plugin-governance
npm run test:integration
# → 4 passing, ~4 min total
```

### What they prove

| Test | Flow | Expected events |
|---|---|---|
| allow a safe tool call | `read` → allow → after-call | `observed → decision → result_recorded → completed → tool_call_completed` |
| block dangerous commands | `exec rm -rf` → block | `observed → decision → result_recorded → completed` |
| round-trip approval | `exec echo` → requireApproval → resolve allow-once → after-call | `observed → decision → approval_requested → execution_suspended → approval_resolved → execution_resumed → result_recorded → completed → tool_call_completed` |
| deny approval | `exec echo` → requireApproval → resolve deny | `observed → decision → approval_requested → execution_suspended → approval_resolved → execution_denied → result_recorded → completed` |

### Prerequisites

The bridge must be buildable from the repo root:

```bash
# From repo root
python3.12 -m venv .venv          # once
source .venv/bin/activate
pip install -e ./kogwistar[server]
pip install -e .                  # pydantic_extension
pip install -r bridge/requirements.txt
```

### Configurable environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BRIDGE_READINESS_TIMEOUT_MS` | `300000` (5 min) | Max wait for `/debug/state → 200` per bridge instance |
| `BRIDGE_REQUEST_TIMEOUT_MS` | `90000` (90 s) | HTTP fetch timeout for each plugin call to the bridge |
| `BRIDGE_TEST_TIMEOUT_MS` | `120000` (2 min) | Per-test timeout in the Node.js runner |

Example — run with tighter timeouts on a fast machine:

```bash
BRIDGE_READINESS_TIMEOUT_MS=60000 \
BRIDGE_REQUEST_TIMEOUT_MS=45000 \
BRIDGE_TEST_TIMEOUT_MS=90000 \
npm run test:integration
```

> **Bridge policy env vars** (`DANGEROUS_TOOLS`, `BLOCK_PATTERNS`, `APPROVAL_PATTERNS`)
> also affect integration test outcomes. See [`.env.example`](../../.env.example).

---

## Why the first bridge request is slow (~30-90 s)

uvicorn's TCP port becomes ready long before the Kogwistar runtime finishes initialising
(Chroma engines + WorkflowRuntime + workflow design install). The harness solves this with
a **readiness probe** — it polls `/debug/state` every 500 ms until it returns 200.
`/healthz` only proves uvicorn is listening; `/debug/state` exercises the store layer.

Once the probe passes, the test's real request hits an already-initialised runtime and
completes quickly.

---

## Developer debug cheatsheet

**Start bridge manually (from repo root):**

```bash
PYTHONPATH=. .venv/bin/python -m uvicorn bridge.app.main:app \
  --host 127.0.0.1 --port 19800
```

**Probe governance (allow path):**

```bash
curl -s -X POST http://127.0.0.1:19800/policy/before-tool-call \
  -H "Content-Type: application/json" \
  -d '{"pluginId":"kogwistar-governance","sessionId":"s","toolName":"read","params":{}}'
```

**Probe governance (block path):**

```bash
curl -s -X POST http://127.0.0.1:19800/policy/before-tool-call \
  -H "Content-Type: application/json" \
  -d '{"pluginId":"kogwistar-governance","sessionId":"s","toolName":"exec","params":{"command":"rm -rf /tmp/x"}}'
```

**Inspect bridge state:**

```bash
curl -s http://127.0.0.1:19800/debug/state | python3 -m json.tool
```

**Run a single integration test by name:**

```bash
node --test --test-name-pattern "allow a safe" \
  test/live-bridge.integration.test.js
```

**Stream bridge stderr during a run** (pass `streamOutput: true` to `startBridge`):

```js
// Temporarily in a test:
const bridge = await startBridge({ streamOutput: true });
```

---

## How to add a new integration test

```js
test("my new scenario", { timeout: BRIDGE_TEST_TIMEOUT_MS }, async (t) => {
  const bridge = await startBridge();
  t.after(() => bridge.stop());
  t.signal.addEventListener("abort", () => bridge.stop(), { once: true });

  const plugin = await loadPluginHandlers({ bridgeUrl: bridge.bridgeUrl });

  // Exercise the hook
  const decision = await plugin.beforeToolCall(
    { toolName: "my_tool", params: { key: "value" }, toolCallId: "call-1" },
    makeContext("my_tool", "sess-1", { toolCallId: "call-1" })
  );

  // Assert on the plugin's decision shape
  assert.deepEqual(decision, {});   // or { block: true, ... }

  // Assert on what the bridge recorded
  const state = await fetchBridgeState(bridge.bridgeUrl);
  assert.deepEqual(
    state.events.map((e) => e.eventType),
    ["governance.tool_call_observed.v1", "governance.decision_recorded.v1", ...]
  );
});
```

---

## Policy customisation

The bridge's `bridge/app/policy.py` controls which tools are allowed, blocked, or held
for approval. To change policy without editing Python:

| Env var | Default | Effect |
|---|---|---|
| `DANGEROUS_TOOLS` | `exec,apply_patch` | Tools always requiring approval |
| `BLOCK_PATTERNS` | `rm -rf,shutdown,reboot` | Param substrings that trigger block |
| `APPROVAL_PATTERNS` | `delete,drop,truncate,chmod 777` | Param substrings requiring approval |
| `APPROVAL_TIMEOUT_MS` | `600000` | Approval request timeout |

```bash
# Example: also block "format" commands
BLOCK_PATTERNS="rm -rf,shutdown,reboot,format" npm run test:integration
```
