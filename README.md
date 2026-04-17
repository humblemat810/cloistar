# Kogwistar × OpenClaw Governance Semantics Layer

**A canonical governance semantics layer for agent systems, with graph-native memory and runtime hooks for OpenClaw.**

This repository connects [Kogwistar](./kogwistar/) (a graph-native agent substrate) to [OpenClaw](https://github.com/openclaw/openclaw) via two plugins and a FastAPI bridge. It is not just hook wiring; it is the semantic execution layer under governed agent actions. It delivers:

- **Governance hooks** — real `allow`, `block`, and `requireApproval` decisions on every tool call
- **Knowledge Graph CRUD** — create, query, redirect, and tombstone nodes/edges from CLI or agent tools
- **Embeddable bridge** — a standalone FastAPI service that any OpenClaw deployment can point at
- A **governance/event semantics layer that agent systems usually hand-wave away**
- A **backbone + semantic-events model** so execution flow and governance meaning stay separate but linked

---

## ⚡ New here? Start with the Quickstart

→ **[QUICKSTART.md](./QUICKSTART.md)** — Docker, local Python, library usage, plugin install, KG reference

---

## What is real today

- OpenClaw plugin hooks post real `before_tool_call`, `after_tool_call`, and approval-resolution payloads to the bridge.
- The bridge returns real `allow`, `block`, and `requireApproval` OpenClaw decisions.
- The bridge hosts an embedded Kogwistar `WorkflowRuntime` for governance decisioning and approval suspend/resume.
- Canonical governance events, receipts, approvals, workflow runs, and latest-state projections are persisted durably through the bridge store/service layer.
- The conversation graph carries semantic governance nodes and edges, including result and terminal completion semantics.
- The bridge exposes real KG CRUD and query endpoints under `/kg/*`, and the KG plugin exposes those as OpenClaw tools and CLI commands.
- Each governed tool call gets one canonical backbone, and semantic governance events attach to that backbone rather than replacing it.
- Two decoupled plugins:
  - `plugin-governance/` — lifecycle hook plugin (governance)
  - `plugin-kg/` — Knowledge Graph CRUD plugin

## Current scope and refinement areas

- The stack is production-capable for local and self-hosted deployments, with a deliberately simple and opinionated governance policy layer rather than a fully enterprise policy engine.
- Kogwistar is the current workflow/graph substrate. Some CDC and runtime trace details therefore follow substrate behavior, but the bridge semantics are intended to stay portable to other runtimes if the substrate changes later.
- Packaging and operator ergonomics are already usable today, but the repo is still tightening the developer/operator experience around install, rebuild, and inspection workflows.
- The graph/query layer is implemented and durable today, and the remaining work is mainly about making query surfaces, demos, and operator-facing inspection paths clearer and easier to use.

## Core Idea

The central design is:

- one canonical backbone per governed tool call
- semantic governance events attached to that backbone
- latest-state projections materialized separately from graph lineage

This means the system keeps three different things distinct:

- execution flow
- governance meaning
- operator/debug latest state

Most agent systems collapse those into one noisy stream. This repo does not.

---

## Repo Layout

```text
.
├── bridge/              FastAPI governance bridge
│   ├── app/
│   │   ├── domain/      governance event append + models
│   │   ├── integrations/ OpenClaw DTO + mapper
│   │   ├── projections/ decision projection
│   │   ├── runtime/     Kogwistar-hosted governance workflow & service
│   │   ├── main.py      entry point + all REST routes (including /kg/*)
│   │   ├── kg_models.py KG CRUD Pydantic DTOs
│   │   ├── policy.py    allow / block / requireApproval logic
│   │   └── store.py     durable bridge-side store
│   ├── tests/
│   └── requirements.txt
├── plugin-governance/   OpenClaw plugin — before/after hook + approval resolution
│   ├── src/
│   ├── openclaw.plugin.json
│   └── package.json
├── plugin-kg/           OpenClaw plugin — KG CRUD tools
│   ├── src/
│   ├── openclaw.plugin.json
│   └── package.json
├── kogwistar/           Kogwistar Python library (git submodule / local dev)
├── scripts/             Helper E2E and demo scripts
├── docker-compose.yml         ← Quickstart: bridge only
├── docker-compose.hardened.yml ← Full stack: bridge + OpenClaw gateway + CLI
├── QUICKSTART.md        ← START HERE
├── kg_integration.md    KG CRUD integration guide
├── architecture.md      Component topology
├── ARD.md               Current project status and near-term direction
├── ARD-persistence.md   Persistence semantics and durability notes
└── openclaw-governance-e2e-quickstart.md  Full operator E2E guide
```

---

## Quick Actions

| If you want to... | Start here | Notes |
| --- | --- | --- |
| Get running in minutes | [`QUICKSTART.md`](./QUICKSTART.md) | Docker or local Python |
| Run the full local helper stack | [`openclaw-governance-e2e-quickstart.md`](./openclaw-governance-e2e-quickstart.md) | Full operator entrypoint |
| Run a live `allow`, `block`, or `approval` demo | [`scripts/run-openclaw-gateway-governance-e2e.sh`](./scripts/run-openclaw-gateway-governance-e2e.sh) | Supports `--demo-case allow\|block\|approval` |
| Use KG CRUD from the CLI | [`kg_integration.md`](./kg_integration.md) | |
| Read the architecture model | [`architecture.md`](./architecture.md) | Backbone, semantics, and bridge boundary |
| Read persistence semantics | [`ARD-persistence.md`](./ARD-persistence.md) | Durable graph + projection model |
| Read future UX direction | [`UX-proposal.md`](./UX-proposal.md) | Operator-facing usability ideas |
| Run the three-terminal E2E harness | [`scripts/run-openclaw-governance-three-terminal.py`](./scripts/run-openclaw-governance-three-terminal.py) | Supports self-starting and attached-stack flows |
| Inspect current bridge state | `GET /debug/state` on the bridge | Use `curl http://localhost:8799/debug/state` |
| Change policy behavior | [`bridge/app/policy.py`](./bridge/app/policy.py) | Controls `allow`, `block`, `requireApproval` |

---

## Packaging

### Bridge (Docker)

Build from the repo root (required — the image bundles the local `kogwistar` source and the bridge app together):

```bash
docker compose build       # builds kogwistar-bridge:local
docker compose up -d       # starts bridge on port 8799
```

### Cloister (Python library)

```bash
# From source (development)
pip install -e .[server]

# From PyPI (once published)
pip install "cloister[server]"
```

### OpenClaw Integration

If OpenClaw is already installed, Cloister can detect it and print the exact plugin install commands:

```bash
cloister install-openclaw
```

If OpenClaw is not installed yet, the same command still writes a local client-side governance config and keeps the bridge usable on its own.

The import namespace remains `kogwistar` internally, but the published Python distribution name is `cloister`.

You can also override the bridge URL when your governance bridge is running somewhere else:

```bash
cloister install-openclaw --bridge-url http://127.0.0.1:8799
```

If you have a local OpenClaw checkout instead of a global CLI install, point the installer at it explicitly:

```bash
cloister install-openclaw --openclaw-home /home/azureuser/cloistar/openclaw
```

That same command also accepts `--openclaw-repo` and `--openclaw-cli` if you want to override the repo path or the CLI binary directly.

### OpenClaw Plugins (NPM)

```bash
cd plugin-governance && npm install && npm run build
cd ../plugin-kg && npm install && npm run build

openclaw extension add ./plugin-governance
openclaw extension add ./plugin-kg
```

---

## Main Runtime Flow

```text
OpenClaw runtime
  -> plugin-governance hook
  -> bridge /policy/before-tool-call
  -> bridge canonicalization and durable store updates
  -> Kogwistar workflow runtime evaluates policy
  -> bridge returns `allow`, `block`, or `requireApproval`
  -> OpenClaw executes, blocks, or suspends
  -> bridge records completion or approval resolution
  -> Kogwistar runtime resumes when approval is granted or denied
```

---

## Development Notes

- Treat OpenClaw as an external immutable runtime boundary.
- Prefer Gateway subscriptions, operator APIs, and compiled runtime surfaces over patching OpenClaw internals.
- Use port **8799** for the bridge. Port 8788 is reserved by host-level processes.
- See [`pitfall.md`](./pitfall.md) for known gotchas around Pydantic, port conflicts, and plugin caching.
