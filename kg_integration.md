# Kogwistar KG CRUD Integration (OpenClaw)

**Core Concept**: This integration exposes the Kogwistar Knowledge Graph (KG) engine as part of the OpenClaw plugin ecosystem. It allows both humans (via CLI) and AI agents (via tools) to perform standard memory CRUD operations (Create, Get, Update, Delete, Query) with full graph integrity (using redirect and tombstone semantics).

## 🚀 Quickstart

### 1. Start the Bridge
Ensure the bridge is running on port **8799**:
```bash
python -m bridge.app.main
```

### 2. Common CLI Commands
Use the `openclaw kg` command group to interact with the KG:

| Task | Command Example |
| :--- | :--- |
| **Create Node** | `openclaw kg node create --label "User" --summary "A person"` |
| **Search Nodes** | `openclaw kg query "search term"` |
| **Get Node** | `openclaw kg node get --ids <id>` |
| **Redirect Node** | `openclaw kg node update <old_id> <new_id>` |
| **Delete Node** | `openclaw kg node delete <id>` |

---

## Technical Overview

### 1. Bridge Layer (FastAPI)
- **Port**: **8799** (avoid conflict with 8788).
- **Endpoints**:
  - `POST /kg/node/...` (create, get, delete, update)
  - `POST /kg/edge/...` (create, get, delete, update)
  - `POST /kg/query` (semantic search)
- **Engine Logic**: Implements Kogwistar-specific `tombstone` (delete) and `redirect` (update) patterns.

### 2. Plugin Layer (TypeScript)
- **Tools**: Registered in `plugin/src/index.ts` for AI agent access (`kg_create_node`, `kg_query`, etc.).
- **CLI**: Registered via `api.registerCli` for human operators.

## Verification

### Demo Script
Run the end-to-end verification script:
```bash
./scripts/demo-kg-crud.sh
```

## Detailed Pitfalls
For implementation "gotchas" regarding caching, log swallowing, and port conflicts, see:
[pitfall.md](./pitfall.md)
