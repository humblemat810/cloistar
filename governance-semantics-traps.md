# Governance Semantics Traps And Failure Notes

This note captures the concrete semantic traps we hit while wiring the
OpenClaw -> bridge -> Kogwistar governance flow, especially once the CDC
conversation viewer forced us to look at the raw graph instead of only
`/debug/state`.

It is meant to prevent future "looks fixed in tests, still broken live"
mistakes.

## Core Invariants

- Every governed tool call must map to one stable `governanceCallId`.
- Every branch must append a clear semantic result.
- Every branch must append a common terminal completion event.
- Every semantic event shown in the graph must have a meaningful next step or be
  an intentional terminal.
- Receipts must attach to the semantic event they actually prove, not the event
  we wish had happened.
- `/debug/state` being correct is not enough; the conversation graph and CDC
  stream must also be correct.

## Trap 1: Projection Correctness Hid Graph Incorrectness

We repeatedly validated:

- canonical events existed
- approvals could be reconstructed
- `/debug/state` looked right

But CDC exposed that the conversation graph still had:

- orphan receipts
- operational status nodes with no semantic value
- suspended branches with no visible result or completion

Lesson:

- never treat projection correctness as proof that graph topology is correct
- pin graph-shape assertions directly

## Trap 2: Operational Rows Polluted The Conversation Graph

`approval_subscription` and similar store records were being written into the
conversation graph as standalone nodes.

That produced misleading CDC views:

- orphan "Approval subscription status" nodes
- graph noise dominating the real governance lineage

Lesson:

- operational/meta/projection records should stay in named projection/meta
- only semantic governance artifacts belong in the conversation graph

## Trap 3: `after_tool_call` Does Not Always Mean Tool Completion

OpenClaw can emit `after_tool_call` with:

- `details.status = approval-pending`

That payload means:

- the attempted tool use reached the approval gate

It does **not** mean:

- the tool completed

Earlier logic incorrectly treated `after_tool_call` as completion-oriented and
left `Receipt after_tool_call` orphaned when no `tool_call_completed` event
existed.

Lesson:

- `after_tool_call approval-pending` must attach to
  `governance.execution_suspended.v1`
- true completion receipts should attach to
  `governance.tool_call_completed.v1`

## Trap 4: Gateway Approval Id And Bridge Approval Id Are Different

The live exec approval flow exposed two different identifiers:

- gateway exec approval id
- bridge approval request id

Assuming they are the same caused real end-to-end linkage failure.

Lesson:

- keep gateway approval ids and bridge approval ids distinct
- use stable governance/tool-call identity to map between them
- use `after_tool_call approval-pending` receipts as the authoritative bridge
  between the gateway exec approval id and the governed tool-call scope

## Trap 5: Real Exec Gateway Payloads Do Not Always Include `toolCallId`

The real live `exec.approval.requested` payload can omit:

- `toolCallId`
- `toolName`

It may only contain request fields like:

- `sessionKey`
- `command`
- `cwd`
- `host`

So "match gateway request to approval by `toolCallId`" is insufficient in live
traffic.

Lesson:

- test against real exec payload shape, not only idealized fixtures
- when request shape is sparse, recover linkage from the
  `after_tool_call approval-pending` receipt path

## Trap 6: Arrival Order Is Not Guaranteed

These can arrive in different orders:

- gateway `exec.approval.requested`
- bridge `approval_requested`
- gateway `exec.approval.resolved`

Because they come through different async paths.

Lesson:

- treat request-first and resolution-first skew as supported orderings
- never assume canonical bridge approval rows exist before gateway events arrive
- pin request-first tests permanently

## Trap 7: The Workflow Can Be Correct While The Backbone Still Looks Broken

The workflow run legitimately stops at the approval step while suspended.

That is normal.

What must still happen after resolution:

- semantic events append
- backbone continues
- workflow/backbone joins remain visible

Lesson:

- distinguish "workflow suspended at step 4" from "semantic graph never resumed"
- do not misdiagnose a real missing resolution append as a harmless suspended
  workflow state

## Trap 8: We Needed A Common End Marker

Without a common completion fact, deny/block branches looked unfinished even
when policy or approval had actually reached a terminal outcome.

Fix:

- `governance.result_recorded.v1`
- `governance.completed.v1`

Lesson:

- `tool_call_completed` is execution-specific, not universal
- every governance call needs a branch-independent semantic end marker

## Trap 9: CDC Can Be Wrong Even When Bridge State Is Right

In this round, `/debug/state` was eventually correct while CDC still looked
wrong for two independent reasons:

- the bridge was not forwarding approval resolution yet
- later, multiple demo stacks were running at once and clobbering the same
  `--stable-run-dir` CDC artifacts

Lesson:

- always compare:
  - live `/debug/state`
  - demo trace
  - gateway log
  - CDC oplog
- do not trust shared `current/` artifacts if more than one stack may be
  running

## Trap 10: The Approval Listener Can Be Alive But Semantically Dead

The bridge-side gateway approval listener was started before pairing settled.

The compiled OpenClaw approvals client resolves gateway auth once at creation.
After an early `pairing required` close, it could remain running with stale auth
and never forward the later `exec.approval.*` events.

This made the bridge look stuck at:

- `governance.execution_suspended.v1`

even though:

- the gateway emitted `exec.approval.requested`
- the LLM approver called `exec.approval.resolve`
- the gateway emitted `exec.approval.resolved`

Lesson:

- after pairing or device approval changes, restart the bridge approval
  subscription listener
- "process still running" is not proof that the listener is healthy

## Trap 11: Repeated Demo Runs Need Stronger Guardrails

Local demo runs introduced several false diagnoses:

- model rendered `exec: echo hello` as plain text
- no real tool call happened
- approval flow never started
- stale run dirs mixed old and new evidence

Lesson:

- fail or warn loudly when:
  - no real tool call happened
  - approval flow triggered but `governance.completed.v1` never appears
- prefer fresh run dirs when validating semantic fixes

## Minimum Regression Set We Should Keep

- request-first gateway exec approval still resolves correctly
- sparse live exec approval request payload still links correctly
- `after_tool_call approval-pending` receipt attaches to
  `governance.execution_suspended.v1`
- before and after receipts from the same tool attempt share governance scope
- deny path appends:
  - `approval_resolved`
  - `execution_denied`
  - `result_recorded`
  - `completed`
- allow path appends:
  - `approval_resolved`
  - `execution_resumed`
  - `result_recorded`
  - `completed`
- CDC verification should be done only against a single fresh stack

## Practical Debug Order

When the graph looks wrong again, check in this order:

1. Does the model make a real tool call at all?
2. Did `before_tool_call` reach the bridge?
3. Did `after_tool_call` carry `approval-pending`?
4. Did the gateway emit `exec.approval.requested`?
5. Did the bridge record a linked `gatewayApprovalId`?
6. Did the approver really call `exec.approval.resolve`?
7. Did the bridge receive the resolution callback?
8. Did `/debug/state` append `approval_resolved`, branch result, and
   `completed`?
9. Is CDC reading the same fresh stack, or are artifacts being clobbered?

If step 8 succeeds and step 9 fails, the remaining problem is CDC delivery or
artifact hygiene, not governance semantics.
