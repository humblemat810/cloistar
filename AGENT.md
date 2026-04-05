# Agent Notes

Concise repo guide for future integration and debugging work.

## Core Invariants

- One governed tool attempt must map to one stable `governanceCallId`.
- Every governance branch must append a semantic result and a common terminal completion.
- `after_tool_call` does not always mean execution completed.
- Projection correctness is not proof of graph correctness.
- Operational/meta rows do not belong in the semantic conversation graph.
- If CDC and `/debug/state` disagree, investigate both; do not trust one alone.

## Semantic Rules

- `before_tool_call` receipt attaches to `governance.tool_call_observed.v1`.
- `after_tool_call` with `approval-pending` attaches to `governance.execution_suspended.v1`.
- True completed `after_tool_call` attaches to `governance.tool_call_completed.v1`.
- Approval resolution receipts attach to `governance.approval_resolved.v1`.
- Deny/block paths must still append:
  - a result event
  - a completion event

## Repeated Traps

- Gateway approval id and bridge approval request id are different. Do not equate them.
- Real `exec.approval.requested` payloads may omit `toolCallId` and `toolName`.
- Gateway request/resolution can arrive before bridge approval rows exist.
- `approval_subscription` and similar status rows are graph pollution if written into conversation.
- A workflow may be correctly suspended while the semantic backbone is still broken.
- Multiple demo stacks using the same `--stable-run-dir` can make CDC evidence look contradictory.
- The approval listener can be alive but semantically dead after pairing/auth changes.
- Models can fake tool calls as plain text. If no real tool call happened, no approval flow happened.

## Fast Debug Order

1. Check bridge state:
   - `/debug/state`
2. Check demo trace:
   - `logs/demo-approval-trace.jsonl`
3. Check gateway logs:
   - `logs/gateway.stdout.log`
   - `logs/gateway.stderr.log`
4. Check CDC oplog:
   - `cdc/oplog/cdc_oplog.jsonl`
5. Confirm only one demo stack is writing to the run dir.

## File Lookups

- Bridge entrypoints:
  - [bridge/app/main.py](/home/azureuser/cloistar/bridge/app/main.py)
- Governance graph persistence:
  - [bridge/app/runtime/governance_service.py](/home/azureuser/cloistar/bridge/app/runtime/governance_service.py)
- Governance workflow design/resolvers:
  - [bridge/app/runtime/governance_design.py](/home/azureuser/cloistar/bridge/app/runtime/governance_design.py)
  - [bridge/app/runtime/governance_resolvers.py](/home/azureuser/cloistar/bridge/app/runtime/governance_resolvers.py)
- Bridge state/linkage:
  - [bridge/app/store.py](/home/azureuser/cloistar/bridge/app/store.py)
- OpenClaw gateway listener:
  - [scripts/lib/openclaw-gateway-approval-listener.mjs](/home/azureuser/cloistar/scripts/lib/openclaw-gateway-approval-listener.mjs)
- Demo helper:
  - [scripts/run-openclaw-gateway-governance-e2e.sh](/home/azureuser/cloistar/scripts/run-openclaw-gateway-governance-e2e.sh)
- CDC bridge/runtime substrate:
  - [kogwistar/kogwistar/cdc/change_bridge.py](/home/azureuser/cloistar/kogwistar/kogwistar/cdc/change_bridge.py)
  - [kogwistar/kogwistar/runtime/runtime.py](/home/azureuser/cloistar/kogwistar/kogwistar/runtime/runtime.py)

## Upstream vs Local

- If the bug involves:
  - `wf_step`
  - `wf_ckpt`
  - `client_sandbox_resume`
  - `wf_next_step_exec`
  - `persist_checkpoint`
  then suspect upstream Kogwistar runtime first.
- If the bug involves:
  - approval linkage
  - receipt anchoring
  - semantic governance events
  - backbone joins
  then suspect bridge code first.

## Known Good Expectations

- Approval-deny flow should show:
  - observed
  - decision
  - approval_requested
  - execution_suspended
  - approval_resolved
  - execution_denied
  - result_recorded
  - completed
- `Receipt after_tool_call` must not be orphaned in `approval-pending` runs.
- Resumed runtime trace should not leave `client_sandbox_resume` or its checkpoint orphaned.

## Useful Companion Note

- For longer history and failure analysis, see:
  - [governance-semantics-traps.md](/home/azureuser/cloistar/governance-semantics-traps.md)
