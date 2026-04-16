# ARD: Current Status and Near-Term Direction

This document now serves as a current-status and near-term-direction note, not
as a pre-runtime roadmap from the earlier bridge seam.

## Current State

The repo already behaves like a real governance boundary:

- OpenClaw emits hook events.
- `plugin-governance/` normalizes them into canonical governance input.
- The bridge decides `allow`, `block`, or `requireApproval`.
- The bridge persists durable governance state and semantic graph structure.
- Approval suspend/resume is hosted by the embedded Kogwistar runtime.
- `plugin-kg/` exposes bridge-backed graph CRUD and query separately from governance.

## Current Pieces

- [plugin-governance/src/index.ts](/home/azureuser/cloistar/plugin-governance/src/index.ts) is the live governance plugin entry.
- [plugin-governance/src/governance-contract.ts](/home/azureuser/cloistar/plugin-governance/src/governance-contract.ts) is the normalization/projection boundary.
- [plugin-governance/src/governance-schema.ts](/home/azureuser/cloistar/plugin-governance/src/governance-schema.ts) defines the internal/wire/debug schema family.
- [plugin-kg/src/index.ts](/home/azureuser/cloistar/plugin-kg/src/index.ts) is the separate KG plugin entry.
- [bridge/app/main.py](/home/azureuser/cloistar/bridge/app/main.py) exposes the governance and `/kg/*` endpoints.
- [bridge/app/store.py](/home/azureuser/cloistar/bridge/app/store.py) and [bridge/app/runtime/governance_service.py](/home/azureuser/cloistar/bridge/app/runtime/governance_service.py) provide the durable store/service layer.
- [bridge/app/runtime/governance_runtime.py](/home/azureuser/cloistar/bridge/app/runtime/governance_runtime.py) hosts the embedded runtime.

## Direction That Is Now Real

The bridge now does host Kogwistar natively:

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

For this use case, OpenClaw is the external actor proposing a tool action, and
Kogwistar is the governor that evaluates the proposal, records it, and either:

- allows it
- blocks it
- suspends for approval and resumes later

That means the bridge stays relatively thin:

- receive the OpenClaw hook payload
- materialize or route it into a Kogwistar workflow run
- let the resolver/workflow decide what graph nodes and edges to create
- map the workflow outcome back into the bridge response contract

## Near-Term Direction

The remaining work is no longer “build the runtime seam at all.” It is:

- tighten operator/debug ergonomics
- keep plugin/runtime/schema boundaries aligned
- improve session-level linking across multiple governed tool calls
- keep CDC/runtime trace continuity clear and substrate-accurate
- continue shrinking deprecated transition shims

## Status Summary

Already real:

- real governance hook enforcement
- real approval suspend/resume
- real durable governance records and projections
- real semantic conversation-graph persistence
- real separate KG plugin and `/kg/*` bridge path

Still worth tightening:

- operator/demo UX
- multi-call/session-level graph linking
- runtime/CDC trace continuity details
- cleanup of deprecated transition files and stale docs

Acceptance criteria:

- One request can be traced through the full seam with a single identifier.
- Debugging one call does not require guessing which log line belongs to which event.

## Immediate Priorities

1. Keep plugin/runtime/schema boundaries aligned as the TypeScript cleanup finishes.
2. Improve operator-facing inspection paths and demo ergonomics.
3. Keep the conversation graph semantically clean while runtime/CDC details continue to mature.
4. Link multiple governed tool-call backbones into clearer session-level views without collapsing them into one backbone.
