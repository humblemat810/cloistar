# Kogwistar × OpenClaw Governance Integration

This repo is no longer just a thin starter scaffold. It now contains a live
OpenClaw plugin, a live FastAPI bridge, an embedded Kogwistar governance
runtime, a durable bridge-side governance store, and runnable integration and
E2E harnesses for `allow`, `block`, and `requireApproval` flows.

The current architecture is still evolving. The bridge/runtime path is real and
testable today, while the final graph-native persistence/read-model design is
still in progress.

## Start Here

- [OpenClaw Governance E2E Quickstart](./openclaw-governance-e2e-quickstart.md)
  Operator-facing setup, live helper commands, approval demos, and LLM approval demo flow.
- [OpenClaw Bridge E2E Status](./openclaw-bridge-e2e-status.md)
  What is currently proven live, what is still hybrid, and what remains missing.
- [Architecture](./architecture.md)
  Current dev topology and the intended OpenClaw/plugin/bridge/Kogwistar seam.
- [ARD](./ARD.md)
  Main roadmap for correctness, observability, tests, and hardening.
- [Persistence ARD](./ARD-persistence.md)
  Roadmap for moving from the current durable bridge store to a fuller graph-native persistent model.
- [Kogwistar Integration Guide](./kogwistar-integration-guide.md)
  How the bridge should host Kogwistar runtime, resolvers, and persistence.

## Current Status

What is real today:

- OpenClaw plugin hooks post real `before_tool_call`, `after_tool_call`, and approval-resolution payloads to the bridge.
- The bridge returns real `allow`, `block`, and `requireApproval` OpenClaw decisions.
- The bridge hosts a real embedded Kogwistar `WorkflowRuntime` for governance decisioning and approval suspend/resume.
- The bridge persists operator-facing governance state through a durable service/store path.
- The repo includes:
  - fast bridge integration tests
  - live three-terminal E2E harnesses
  - self-starting and attached-stack E2E modes
  - demo-only approval tracing via `sys.monitoring`

What is not final yet:

- The persistence architecture is still hybrid, not yet the final graph-native read model.
- The bridge still uses a local governance policy implementation, not a production policy engine.
- The repo is still refining restart/rebuild/query semantics around the durable store and graph artifacts.

## Quick Actions

| If you want to... | Start here | Notes |
| --- | --- | --- |
| Run the full local helper stack | [`openclaw-governance-e2e-quickstart.md`](./openclaw-governance-e2e-quickstart.md) | Best operator entrypoint. |
| Run a live `allow`, `block`, or `approval` demo | [`scripts/run-openclaw-gateway-governance-e2e.sh`](./scripts/run-openclaw-gateway-governance-e2e.sh) | Supports `--demo-case allow|block|approval`. |
| Run the three-terminal E2E harness | [`scripts/run-openclaw-governance-three-terminal.py`](./scripts/run-openclaw-governance-three-terminal.py) | Supports self-starting and attached-stack flows. |
| Demo LLM approval | [`openclaw-governance-e2e-quickstart.md`](./openclaw-governance-e2e-quickstart.md) | Use `approval --approval-mode llm`. |
| Emit a dedicated approval demo trace file | [`scripts/run-openclaw-gateway-governance-e2e.sh`](./scripts/run-openclaw-gateway-governance-e2e.sh) | Add `--demo-probe` to write `demo-approval-trace.jsonl`. |
| Inspect current bridge state | [`bridge/app/main.py`](./bridge/app/main.py) | Use `/debug/state`. |
| Change policy behavior | [`bridge/app/policy.py`](./bridge/app/policy.py) | Controls `allow`, `block`, `requireApproval`. |
| Inspect runtime suspend/resume logic | [`bridge/app/runtime/governance_runtime.py`](./bridge/app/runtime/governance_runtime.py) | Native Kogwistar workflow host. |
| Inspect durable governance store behavior | [`bridge/app/runtime/governance_service.py`](./bridge/app/runtime/governance_service.py) and [`bridge/app/store.py`](./bridge/app/store.py) | Bridge-facing durable store facade. |
| Inspect plugin hook wiring | [`plugin/src/index.ts`](./plugin/src/index.ts) | OpenClaw hook entrypoint. |

## Quick Start

### Fastest live helper run

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b
```

### Fastest approval demo

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --stable-run-dir \
  --ollama-model qwen3:4b \
  --demo-case approval
```

### Approval demo with dedicated demo trace

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --stable-run-dir \
  --demo-probe \
  --ollama-model qwen3:4b \
  --demo-case approval
```

### Fast in-process bridge integration tests

```bash
/home/azureuser/cloistar/.venv/bin/python -m pytest bridge/tests/test_policy_matrix_pytest.py -q
```

### Focused demo-probe tests

```bash
/home/azureuser/cloistar/.venv/bin/python -m pytest bridge/tests/test_demo_approval_probe.py -q
```

### Live three-terminal E2E matrix

```bash
OPENCLAW_RUN_E2E=1 /home/azureuser/cloistar/.venv/bin/python -m pytest bridge/tests/test_openclaw_three_terminal_e2e.py -q
```

## Repo Layout

```text
.
├── bridge/
│   ├── app/
│   │   ├── demo/
│   │   │   ├── approval_probe.py
│   │   │   └── launch_bridge_with_probe.py
│   │   ├── domain/
│   │   │   ├── governance_append.py
│   │   │   └── governance_models.py
│   │   ├── integrations/
│   │   │   ├── openclaw_dto.py
│   │   │   └── openclaw_mapper.py
│   │   ├── projections/
│   │   │   └── openclaw_projection.py
│   │   ├── runtime/
│   │   │   ├── governance_design.py
│   │   │   ├── governance_graph.py
│   │   │   ├── governance_resolvers.py
│   │   │   ├── governance_runtime.py
│   │   │   └── governance_service.py
│   │   ├── main.py
│   │   ├── policy.py
│   │   └── store.py
│   ├── tests/
│   │   ├── test_bridge_contract.py
│   │   ├── test_demo_approval_probe.py
│   │   ├── test_governance_service.py
│   │   ├── test_openclaw_three_terminal_e2e.py
│   │   ├── test_openclaw_three_terminal_existing_stack_e2e.py
│   │   └── test_policy_matrix_pytest.py
│   └── requirements.txt
├── plugin/
│   ├── src/
│   │   ├── governance-contract.ts
│   │   ├── index.ts
│   │   └── kogwistar-client.ts
│   ├── dist/
│   ├── openclaw.plugin.json
│   └── package.json
├── scripts/
│   ├── lib/
│   │   ├── openclaw-gateway-approval-listener.mjs
│   │   └── openclaw-governance-harness.mjs
│   ├── manual-governance-smoke.mjs
│   ├── run-guarded-bridge-test.sh
│   ├── run-openclaw-gateway-governance-e2e.sh
│   ├── run-openclaw-governance-three-terminal.py
│   └── run-safe-governance-resume-probe.sh
├── architecture.md
├── ARD.md
├── ARD-persistence.md
├── kogwistar-integration-guide.md
├── openclaw-bridge-e2e-status.md
└── openclaw-governance-e2e-quickstart.md
```

## Main Runtime Flow

OpenClaw runtime
  -> plugin hook
  -> bridge `/policy/before-tool-call`
  -> bridge canonicalization and durable store updates
  -> Kogwistar workflow runtime evaluates policy
  -> bridge returns `allow`, `block`, or `requireApproval`
  -> OpenClaw executes, blocks, or suspends
  -> bridge records completion or approval resolution
  -> Kogwistar runtime resumes when approval is granted or denied

## Recommended Operator Entry Points

- Human operator testing:
  Use [openclaw-governance-e2e-quickstart.md](./openclaw-governance-e2e-quickstart.md).
- Live status / reality check:
  Use [openclaw-bridge-e2e-status.md](./openclaw-bridge-e2e-status.md).
- Design / roadmap review:
  Use [architecture.md](./architecture.md), [ARD.md](./ARD.md), and [ARD-persistence.md](./ARD-persistence.md).

## Notes

- Treat OpenClaw as an external immutable runtime boundary in this repo.
- Prefer Gateway subscriptions, operator APIs, and compiled runtime surfaces over patching OpenClaw internals.
- The current recommended human start point is the quickstart, not the older Docker-first scaffold flow.
- The current bridge stack is runnable and useful today, but the persistence and graph-read-model story is still under active development.
