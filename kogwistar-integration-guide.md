# Kogwistar Integration Guide

This guide explains how this scaffold should integrate Kogwistar in the medium term, using Kogwistar's native engine, workflow runtime, and resolver model instead of a custom governance loop.

## Purpose

The current scaffold has:

- a host-side OpenClaw plugin
- a thin bridge service
- an in-memory policy stub => changed to kogwistar persistence

That is enough for early seam validation, but it is not the intended long-term architecture.

The intended direction is:

- the bridge hosts Kogwistar directly
- Kogwistar workflow runtime evaluates governance proposals
- Kogwistar persists graph artifacts and execution trace
- the bridge only maps HTTP requests into workflow runs and maps workflow outcomes back into OpenClaw decisions

The conversation graph is part of this too:

- it can store the governance history of the interaction
- it can represent the conversation between the bridge user, the OpenClaw agent, and the governor
- it is a useful projection layer for what was proposed, what was blocked, and what was approved

## Primary Sources

These are the main files worth reading before implementing the deeper integration:

- [AI runtime workflow guide](/home/azureuser/cloistar/kogwistar/docs/ai_runtime_workflow_guide.md)
- [Runtime Level 1 resolvers tutorial](/home/azureuser/cloistar/kogwistar/docs/tutorials/runtime-level-1-resolvers.md)
- [Workflow runtime](/home/azureuser/cloistar/kogwistar/kogwistar/runtime/runtime.py)
- [Resolver registry](/home/azureuser/cloistar/kogwistar/kogwistar/runtime/resolvers.py)
- [Conversation default resolver pack](/home/azureuser/cloistar/kogwistar/kogwistar/conversation/resolvers.py)
- [Conversation workflow designer](/home/azureuser/cloistar/kogwistar/kogwistar/conversation/designer.py)
- [Conversation orchestrator runtime wiring](/home/azureuser/cloistar/kogwistar/kogwistar/conversation/conversation_orchestrator.py)
- [Current roadmap and ARD](/home/azureuser/cloistar/ARD.md)

## Core Idea

The bridge should not invent its own orchestration framework.

Kogwistar already has:

- `GraphKnowledgeEngine` for graph storage and mutation
- `WorkflowRuntime` for persisted workflow execution
- `MappingStepResolver` for named step handlers
- `_deps` injection for runtime dependencies
- `RunSuccess`, `RunFailure`, and `RunSuspended` for step outcomes
- graph-backed workflow design and trace persistence

So the correct integration shape is:

1. OpenClaw plugin sends governance proposal to the bridge.
2. The bridge creates or resumes a Kogwistar workflow run.
3. Resolver steps build graph state, inspect policy context, and decide.
4. The runtime persists trace and state transitions.
5. The bridge maps the workflow outcome to:
   - `allow`
   - `block`
   - `requireApproval`

## Why Not Use The MCP Server

For this integration, the MCP server is the wrong entrypoint.

The bridge can directly import and host Kogwistar because:

- it needs internal engine and runtime access
- it needs direct control over workflow start and resume
- it needs low-overhead decision latency
- it only needs a narrow governance adapter, not the broader external MCP surface

Using direct imports keeps the path simpler:

- `bridge -> Kogwistar engine -> Kogwistar workflow runtime -> resolver pack`

instead of:

- `bridge -> MCP facade -> service layer -> runtime`

## Kogwistar Runtime Model

The Kogwistar runtime model is the key mental model to keep in mind.

### Workflow design

Workflow nodes and edges are persisted graph artifacts.

A workflow design:

- names the steps
- defines routing and branching
- may use explicit fanout and explicit join nodes
- is reusable across runs

### Step handlers

Handlers are registered by op name on `MappingStepResolver`.

Each handler:

- receives `StepContext`
- reads state from `ctx.state_view`
- may mutate state via `ctx.state_write`
- may emit custom events via `StepContext.events`
- must return `RunSuccess`, `RunFailure`, or `RunSuspended`

### Dependency injection

Dependencies are supplied in:

- `initial_state["_deps"]`

That is how the runtime passes in:

- engines
- services
- helper objects
- policy evaluators
- agent wrappers

It is important to note that it need to be injected on deserializing and striped in serializing for transport and persistence.
This is important because governance-specific code should live in resolver functions, not in raw bridge endpoints.

### Execution trace

`WorkflowRuntime` persists checkpoints and step execution trace while it runs.

That means:

- governance is traceable
- approval can be modeled as suspension and resume
- replay and CDC can be built on top of native runtime artifacts

In practice we should think about two graph layers:

- the conversation graph, which stores the governance history in human-readable form
- the workflow trace graph, which stores the execution history of the governance run

## Mapping This To OpenClaw Governance

OpenClaw has three main events in this scaffold:

- `before_tool_call`
- `after_tool_call`
- approval resolution

These map naturally into Kogwistar workflow interactions.

### `before_tool_call`

This is the main governance proposal.

The bridge should:

- receive the OpenClaw payload
- start or reuse a governance workflow run
- inject dependencies and initial state
- execute the next workflow step(s)
- return a mapped decision

The payload may come from a bridge-side user or agent action such as:

- `rm -rf /`
- `shutdown now`
- `chmod 777 /some/path`

The governance workflow should understand the command meaning, not just the raw string. For example, `rm -rf /` is a destructive Unix command and should normally be disapproved or require explicit approval depending on policy.

### `after_tool_call`

This is a completion or audit event.

The bridge should:

- append or project completion state into Kogwistar
- link it to the prior proposal or approval flow
- update conversation or governance trace nodes

The completion event should make the execution history visible in the graphs, not only in logs.

### Approval resolution

This should resume a suspended workflow run.

The bridge should:

- locate the suspended governance run
- resume it with approval resolution state
- let the workflow continue to final decision closure
- return `ok` to the plugin

## Proposed Governance Workflow

The governance workflow should be a first-class Kogwistar workflow design.

Suggested steps:

1. `ingest_proposal`
2. `load_prior_context`
3. `interpret_command`
4. `classify_risk`
5. `check_existing_policy`
6. `decide_governance`
7. `request_approval` or `record_block` or `record_allow`
8. `close_run`

### Example semantics

- `ingest_proposal`
  - create graph nodes or state entries representing the proposed OpenClaw action
- `load_prior_context`
  - inspect prior related actions, approvals, or user policies
- `interpret_command`
  - understand the semantic meaning of a shell command or tool call, for example detecting that `rm -rf /` is destructive
- `classify_risk`
  - determine whether the action is harmless, risky, or high-risk
- `check_existing_policy`
  - inspect configured rules or prior graph-derived preferences
- `decide_governance`
  - return allow, block, or suspend-for-approval
- `request_approval`
  - persist approval request state and return `RunSuspended`
- `record_block`
  - persist the block reason and return success state mapped to `block`
- `record_allow`
  - persist the allow decision and return success state mapped to `allow`

## Graph Model Suggestion

This is still design work, but a practical first model would include:

- proposal node
- bridge user node
- OpenClaw agent node
- governor decision node
- decision node
- approval request node
- approval resolution node
- completion node

and edges such as:

- `proposed`
- `sent_by`
- `governed_by`
- `decided`
- `requires_approval`
- `resolved_by`
- `completed_as`
- `governs`

Important point:

the workflow trace and the graph projection do not need to be the same artifact.

Kogwistar can:

- keep execution history in workflow trace
- project stable governance entities into graph nodes and edges
- keep the conversation graph as a readable governance history of what the bridge user asked, how the governor interpreted it, and what OpenClaw did next

## Bridge Responsibilities

The bridge should stay thin and predictable.

It should do four things:

1. Validate incoming HTTP payloads.
2. Translate payloads into workflow state and `_deps`.
3. Execute or resume Kogwistar workflow runs.
4. Translate workflow outcomes back into the OpenClaw contract.

It should not:

- own the real governance policy logic
- own a second orchestration framework
- become a parallel event store that drifts from Kogwistar

## OpenClaw Contract Mapping

The bridge response still needs to match what the plugin expects.

### Workflow result to bridge result

- `RunSuccess` with final state `decision=allow`
  - bridge returns `{ "decision": "allow" }`
- `RunSuccess` with final state `decision=block`
  - bridge returns `{ "decision": "block", "reason": "..." }`
- `RunSuspended`
  - bridge returns `requireApproval` payload including approval metadata
- `RunFailure`
  - bridge returns a failure path based on the chosen fail-open or fail-closed policy

### Plugin result to OpenClaw hook result

- `allow`
  - plugin returns empty object and OpenClaw proceeds
- `block`
  - plugin returns `{ block: true, blockReason: ... }`
- `requireApproval`
  - plugin returns the approval object and resolution callback

## CDC And Persistence Direction

The cleanest CDC story is to build on Kogwistar-native persistence rather than keep a separate bridge-local event store.

That means:

- workflow trace is the source of execution history
- graph projection becomes the source of durable governance entities
- replay should reconstruct governance state from persisted trace and graph artifacts

Near-term:

- keep `/debug/state`
- add bridge logs
- add graph projection for governance entities

Mid-term:

- persist governance runs durably through Kogwistar
- rebuild state from trace/projection
- make approval and decision history queryable

## Suggested Implementation Sequence

1. Add bridge-side structured logs and correlation ids.
2. Replace `decide(...)` with a Kogwistar runtime wrapper.
3. Create a small governance workflow design.
4. Create a governance resolver pack.
5. Map `RunSuccess` / `RunSuspended` back into bridge responses.
6. Add approval resume handling.
7. Add graph projection for proposals, decisions, and approvals.
8. Add tests for the seam and the workflow path.

## Minimal Pseudocode

This is intentionally schematic, not ready-to-run code.

```python
engine = GraphKnowledgeEngine(...)
resolver = MappingStepResolver()

@resolver.register("ingest_proposal")
def ingest_proposal(ctx):
    deps = ctx.state_view["_deps"]
    governance_service = deps["governance_service"]
    governance_service.add_proposal_nodes(ctx.state_view)
    return RunSuccess(conversation_node_id=None, state_update=[], _route_next=["decide"])

@resolver.register("decide")
def decide(ctx):
    risk = classify(ctx.state_view)
    if risk == "block":
        return RunSuccess(
            conversation_node_id=None,
            state_update=[("u", {"decision": "block", "reason": "dangerous action"})],
            _route_next=["record_block"],
        )
    if risk == "approval":
        return RunSuspended(conversation_node_id=None, state_update=[("u", {"decision": "requireApproval"})])
    return RunSuccess(
        conversation_node_id=None,
        state_update=[("u", {"decision": "allow"})],
        _route_next=["record_allow"],
    )

runtime = WorkflowRuntime(
    workflow_engine=engine,
    conversation_engine=engine,
    step_resolver=resolver,
    predicate_registry={"always": lambda workflow_info, st, r: True},
)
```

## Open Questions

These still need explicit design decisions:

- Should governance project into the conversation graph, a dedicated governance graph, or both?
- What is the canonical graph schema for proposal, decision, approval, and completion?
- How should approval resume keys be stored and looked up?
- What should happen when Kogwistar is unavailable: fail closed or fail open?
- Which state belongs only in workflow trace and which should be promoted into stable graph nodes?

## Recommended Reading Order

If you revisit this later, this is the fastest sequence:

1. [ARD](/home/azureuser/cloistar/ARD.md)
2. [Architecture](/home/azureuser/cloistar/architecture.md)
3. [AI runtime workflow guide](/home/azureuser/cloistar/kogwistar/docs/ai_runtime_workflow_guide.md)
4. [Resolver tutorial](/home/azureuser/cloistar/kogwistar/docs/tutorials/runtime-level-1-resolvers.md)
5. [Workflow runtime](/home/azureuser/cloistar/kogwistar/kogwistar/runtime/runtime.py)
6. [Conversation resolvers](/home/azureuser/cloistar/kogwistar/kogwistar/conversation/resolvers.py)
7. [Conversation orchestrator wiring](/home/azureuser/cloistar/kogwistar/kogwistar/conversation/conversation_orchestrator.py)
