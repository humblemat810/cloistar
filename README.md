# Kogwistar × OpenClaw Governance Integration

**Graph-native agent governance and knowledge memory for OpenClaw.**

This repository connects [Kogwistar](./kogwistar/) (a graph-native agent substrate) to [OpenClaw](https://github.com/openclaw/openclaw) via two plugins and a FastAPI bridge. It delivers:

- **Governance hooks** — real `allow`, `block`, and `requireApproval` decisions on every tool call
- **Knowledge Graph CRUD** — create, query, redirect, and tombstone nodes/edges from CLI or agent tools
- **Embeddable bridge** — a standalone FastAPI service that any OpenClaw deployment can point at

---

## ⚡ New here? Start with the Quickstart

→ **[QUICKSTART.md](./QUICKSTART.md)** — Docker, local Python, library usage, plugin install, KG reference

---

## What is real today

- OpenClaw plugin hooks post real `before_tool_call`, `after_tool_call`, and approval-resolution payloads to the bridge.
- The bridge returns real `allow`, `block`, and `requireApproval` OpenClaw decisions.
- The bridge hosts an embedded Kogwistar `WorkflowRuntime` for governance decisioning and approval suspend/resume.
- Two decoupled plugins:
  - `plugin-governance/` — lifecycle hook plugin (governance)
  - `plugin-kg/` — Knowledge Graph CRUD plugin

## What is not final yet

- Persistence is still hybrid, not yet the final graph-native read model.
- The bridge still uses a local governance policy implementation, not a production policy engine.
- The repo is still refining restart/rebuild/query semantics around the durable store and graph artifacts.

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
├── pydantic_extension/  Local pydantic_extension dev copy
├── scripts/             Helper E2E and demo scripts
├── docker-compose.yml         ← Quickstart: bridge only
├── docker-compose.hardened.yml ← Full stack: bridge + OpenClaw gateway + CLI
├── QUICKSTART.md        ← START HERE
├── kg_integration.md    KG CRUD integration guide
├── architecture.md      Component topology
├── ARD.md               Main roadmap
├── ARD-persistence.md   Persistence roadmap
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
| Run the three-terminal E2E harness | [`scripts/run-openclaw-governance-three-terminal.py`](./scripts/run-openclaw-governance-three-terminal.py) | Supports self-starting and attached-stack flows |
| Inspect current bridge state | `GET /debug/state` on the bridge | Use `curl http://localhost:8799/debug/state` |
| Change policy behavior | [`bridge/app/policy.py`](./bridge/app/policy.py) | Controls `allow`, `block`, `requireApproval` |

---

## Packaging

### Bridge (Docker)

Build from the repo root (required — the image bundles `kogwistar` and `pydantic_extension`):

```bash
docker compose build       # builds kogwistar-bridge:local
docker compose up -d       # starts bridge on port 8799
```

### Kogwistar (Python library)

```bash
# From source (development)
pip install -e ./kogwistar[server]

# From PyPI (once published)
pip install "kogwistar[server]"
```

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
