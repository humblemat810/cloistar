# ARD: OpenClaw and Kogwistar Dev Integration Roadmap

This document captures the near-term roadmap for making the OpenClaw plugin seam correct, observable, and safe in dev.

## Goal

Make the current dev integration behave like a real governance boundary:

- OpenClaw emits hook events.
- The plugin intercepts those events and asks Kogwistar for a decision.
- The bridge decides `allow`, `block`, or `requireApproval`.
- OpenClaw honors that decision and does not proceed when it should not.
- The bridge records what happened so the seam is easy to debug.

## Current Pieces

- `plugin/src/index.ts` registers the plugin entry and the `before_tool_call` / `after_tool_call` hooks.
- `plugin/src/kogwistar-client.ts` posts hook payloads to the bridge.
- `bridge/app/main.py` exposes the governance endpoints and in-memory debug state.
- `scripts/install-plugin-host.sh` registers the local plugin into the checked-out OpenClaw host.
- `dev-debug-cycle.md` describes the current dev loop.

## Roadmap

### Phase 1: Bridge observability

Add structured, human-readable logging in the bridge for every governance request.

Log at least:

- endpoint name
- request id or correlation id
- plugin id
- session id
- tool name
- returned decision
- approval id when present

Keep `/debug/state` as the machine-readable truth, but add logs so the seam can be traced quickly in a terminal.

Acceptance criteria:

- One `before_tool_call` request shows up in logs.
- One returned decision is visible in logs.
- Approval resolution, when present, is visible in logs.

### Phase 2: Plugin enforcement

Make sure the plugin translates bridge decisions into the correct OpenClaw behavior.

Expected behavior:

- `allow` means the tool call continues.
- `block` means OpenClaw does not execute the tool call.
- `requireApproval` pauses execution and routes resolution back through the bridge.

Acceptance criteria:

- A bridge `block` prevents the tool from running.
- A bridge `requireApproval` pauses the action until approval is resolved.
- A bridge `allow` does not add extra friction.

### Phase 3: Kogwistar decider

Turn the bridge into a real policy engine instead of just a pass-through.

Define the decision contract in one place:

- input: plugin id, tool name, params, session metadata, raw event
- output: `allow`, `block`, or `requireApproval`

Start with simple rules:

- allowlist rules
- block rules
- approval thresholds

Later, evolve toward richer policy evaluation and durable storage.

Acceptance criteria:

- The bridge decision is deterministic for the same input.
- The bridge can explain why a decision was made.
- Approval requests carry enough metadata to resolve back to the original request.

### Phase 4: Contract alignment

Keep the manifest, runtime entry, and install helper aligned.

Files to keep consistent:

- `plugin/package.json`
- `plugin/openclaw.plugin.json`
- `plugin/src/index.ts`
- `scripts/install-plugin-host.sh`

What must line up:

- plugin id
- plugin name
- config schema
- extension entrypoint
- install/enable id

Acceptance criteria:

- No stale plugin-id warnings in `~/.openclaw/openclaw.json`.
- OpenClaw installs and enables the plugin using one canonical id.
- Manifest validation does not drift from runtime behavior.

### Phase 5: Tests

Add tests that prove the seam works before we rely on manual inspection.

Minimum tests:

- plugin unit test for `before_tool_call`
- bridge endpoint test for `/policy/before-tool-call`
- bridge endpoint test for `/events/after-tool-call`
- bridge endpoint test for `/approval/resolution`
- one end-to-end smoke test for the whole path

Acceptance criteria:

- The plugin test proves `allow`, `block`, and `requireApproval` behavior.
- The bridge tests prove the endpoints store and return the expected data.
- The smoke test proves the whole path from OpenClaw hook to bridge decision and back.

### Phase 6: Failure handling

Decide what happens when the bridge is unavailable or times out.

Questions to settle:

- Should the plugin fail closed for risky actions?
- Should it fail open for harmless actions?
- Should that be configurable per plugin or per tool?

Acceptance criteria:

- Bridge timeouts have an explicit policy.
- Network failures do not produce ambiguous behavior.
- The chosen default is documented.

### Phase 7: Traceability

Add a trace id or correlation id that follows one tool call across:

- OpenClaw hook event
- plugin payload
- bridge request and response
- bridge state/logs

This is more useful than a plugin-side file logger alone.

Acceptance criteria:

- One request can be traced through the full seam with a single identifier.
- Debugging one call does not require guessing which log line belongs to which event.

### Phase 8: Security and payload hygiene

Tighten what gets logged and how much data is exposed.

Decisions to make:

- whether to redact sensitive params in logs
- whether local-only loopback is the only allowed dev transport
- whether the bridge should accept only the expected plugin id

Acceptance criteria:

- Sensitive payloads are not accidentally printed in full.
- Dev transport is explicit and local.
- The bridge rejects unexpected caller shapes if needed.

### Phase 9: Durable backend later

Keep durable Kogwistar storage and projections as a later milestone.

Do not let the current dev path imply that persistence is already complete.

Acceptance criteria:

- The current dev flow stays in-memory and simple.
- Durable storage is documented as future work, not assumed behavior.

## Recommended Order

1. Contract alignment
2. Bridge observability
3. Plugin enforcement
4. Tests
5. Failure handling
6. Traceability
7. Security and payload hygiene
8. Durable backend later

## Definition of Done for Dev Seam

We can say the seam is correct when all of these are true:

- OpenClaw loads the local plugin successfully.
- The plugin intercepts `before_tool_call`.
- The bridge returns `allow`, `block`, or `requireApproval` correctly.
- OpenClaw respects that decision.
- Approval resolution flows back through the bridge.
- Bridge logs and `/debug/state` make the flow easy to inspect.
- The dev runbook explains how to reproduce the loop from scratch.

