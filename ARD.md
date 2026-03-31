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

## Kogwistar-Native Direction

The preferred next step is not to build a separate governance loop from scratch inside the bridge.

Instead, the bridge should host Kogwistar natively:

- import `kogwistar.engine_core.engine.GraphKnowledgeEngine` directly
- avoid the Kogwistar MCP server for this integration path
- construct a `WorkflowRuntime`
- use a `MappingStepResolver` or a dedicated governance resolver pack
- inject dependencies through `initial_state["_deps"]`
- persist workflow design, execution trace, and graph mutations through the engine

This follows the way Kogwistar already structures runtime execution today:

- workflow nodes and edges live in the workflow graph
- step handlers are registered on a resolver registry
- handlers return `RunSuccess`, `RunFailure`, or `RunSuspended`
- the runtime persists checkpoints and execution traces while executing the workflow design
- resolvers build or mutate graph state by calling engine add-node / add-edge paths through injected services

For this use case, the governing workflow should be modeled as a conversation or workflow between:

- the OpenClaw agent side
- the governor side

OpenClaw is the external actor proposing a tool action. Kogwistar is the governor that evaluates the proposal, records it, and either:

- allows it
- blocks it
- suspends for approval and resumes later

That means the bridge can stay thin:

- receive the OpenClaw hook payload
- materialize or route it into a Kogwistar workflow run
- let the resolver/workflow decide what graph nodes and edges to create
- map the workflow outcome back into the bridge response contract

## Proposed Governance Workflow Shape

The governance loop should look like a native Kogwistar workflow, not a hand-coded polling loop.

Suggested flow:

1. A bridge endpoint receives `before_tool_call`.
2. The bridge creates or reuses a Kogwistar workflow design for governance.
3. The bridge starts a `WorkflowRuntime` run with injected dependencies in `_deps`.
4. Resolver steps:
   - ingest the OpenClaw proposal as graph state
   - append governance/event nodes and edges
   - inspect prior approvals, policies, and history
   - decide `allow`, `block`, or `suspend for approval`
5. The workflow returns:
   - `RunSuccess` mapped to `allow` or `block`
   - `RunSuspended` mapped to `requireApproval`
6. The bridge returns the mapped decision to the plugin.
7. Approval resolution re-enters the workflow as another event and resumes or closes the governance run.

This uses Kogwistar the way its runtime tutorials and conversation workflows already work:

- resolver registration for named ops
- workflow design as persisted graph artifacts
- `_deps` as dependency injection
- `StepContext.events` and trace persistence for observability
- explicit suspend/resume instead of bespoke approval bookkeeping

## Design Implications

This changes the target architecture in a useful way:

- the bridge is primarily an HTTP adapter plus Kogwistar host
- governance policy lives in workflow design and resolvers
- approvals become runtime suspension and resume events
- graph persistence and traceability come from Kogwistar runtime and engine paths
- future CDC/replay should build on Kogwistar traces and projections, not a separate custom governance store

## What Still Needs Definition

Even with this direction clarified, these pieces still need to be designed explicitly:

- the governance workflow design itself
- the resolver pack for governance-specific ops
- the graph schema for OpenClaw proposal, decision, approval, and completion events
- how approval resume keys map back to workflow runs
- whether governance lives in the conversation graph, workflow trace graph, or a dedicated graph namespace
- how bridge endpoints map workflow outcomes back into the exact OpenClaw response contract

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

### Phase 3: Kogwistar-native governance runtime

Replace the hard-coded bridge decider with a Kogwistar-hosted workflow runtime.

Implement:

- direct bridge-side import of `GraphKnowledgeEngine`
- runtime construction without MCP server dependency
- a governance workflow design
- a governance resolver registry
- injected dependencies through `_deps`
- workflow outcomes mapped back into `allow`, `block`, or `requireApproval`

Acceptance criteria:

- The bridge can execute a governance workflow run for a tool proposal.
- The decision comes from resolver/workflow execution, not only a hard-coded `decide(...)`.
- Approval can be represented as workflow suspension and later resolution.
- The bridge can explain which workflow step or graph state produced the decision.

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

### Phase 9: CDC persistence and replay

Build durable persistence on top of Kogwistar's trace and graph model rather than a separate bridge-local event store.

Target:

- persist proposal, decision, approval, and completion events as graph artifacts or trace-linked projections
- support replay and projection rebuild
- keep provenance between OpenClaw request, governance workflow run, and final decision

Acceptance criteria:

- Governance events survive process restart once durable backend wiring is enabled.
- Approval and decision history can be replayed or queried from persisted state.
- CDC/replay uses Kogwistar-native artifacts rather than a custom duplicate log.

## Recommended Order

1. Contract alignment
2. Bridge observability
3. Kogwistar-native governance runtime
4. Plugin enforcement
5. Tests
6. Failure handling
7. Traceability
8. Security and payload hygiene
9. CDC persistence and replay

## Definition of Done for Dev Seam

We can say the seam is correct when all of these are true:

- OpenClaw loads the local plugin successfully.
- The plugin intercepts `before_tool_call`.
- The bridge returns `allow`, `block`, or `requireApproval` correctly.
- OpenClaw respects that decision.
- Approval resolution flows back through the bridge.
- Bridge logs and `/debug/state` make the flow easy to inspect.
- The dev runbook explains how to reproduce the loop from scratch.
