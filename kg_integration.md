# Kogwistar KG CRUD Integration (OpenClaw)

**Core Concept**: This integration exposes the Kogwistar Knowledge Graph (KG) engine via the dedicated `kogwistar-kg` OpenClaw plugin. It allows both humans (via CLI) and AI agents (via tools) to perform standard memory CRUD operations — Create, Get, Update, Delete, and Query — using Kogwistar's graph-native redirect and tombstone semantics.

---

## 🚀 Quickstart

### 1. Start the Bridge
The bridge must be running before any KG operations. Run it from the project root:

```bash
cd bridge
.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8799
```

> **Note**: The bridge uses port **8799**. Port 8788 is reserved by a host-level process and will cause silent failures.

### 2. Verify the Bridge is Up

```bash
curl -s -X POST http://127.0.0.1:8799/kg/node/get \
  -H "Content-Type: application/json" \
  -d '{"limit": 1}'
# Expected: {"ok":true,"nodes":[...]}
```

### 3. Common CLI Commands

The `kogwistar-kg` plugin registers the `openclaw kg` command group:

| Task | Command |
| :--- | :--- |
| **Create a node** | `openclaw kg node create --label "User" --type entity --summary "A person"` |
| **Create an edge** | `openclaw kg edge create --relation "knows" --source-ids <id1> --target-ids <id2>` |
| **Semantic search** | `openclaw kg query "open-source agent"` |
| **Get node by ID** | `openclaw kg node get --ids <id>` |
| **Redirect node** | `openclaw kg node update <old_id> <new_id>` |
| **Tombstone node** | `openclaw kg node delete <id>` |

### 4. Run the End-to-End Demo

```bash
./scripts/demo-kg-crud.sh
```

Expected output walks through all 7 steps: node creation, edge creation, semantic query, get by ID, redirect, tombstone, and final integrity check.

---

## Plugin Architecture

This integration is split into two distinct OpenClaw plugins:

| Plugin | ID | Directory | Responsibility |
| :--- | :--- | :--- | :--- |
| **Governance** | `kogwistar-governance` | `plugin-governance/` | OpenClaw life-cycle hooks: `before_tool_call`, `after_tool_call`, approval resolution |
| **KG** | `kogwistar-kg` | `plugin-kg/` | Knowledge Graph CRUD — node/edge creation, querying, redirect, and tombstone |

Both plugins communicate with the same bridge (`bridge/`) running on port **8799**.

---

## Bridge Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/kg/node/create` | `POST` | Create a node with grounding |
| `/kg/node/get` | `POST` | Retrieve nodes by ID or filter |
| `/kg/node/update` | `POST` | Redirect an old node to a new one |
| `/kg/node/delete` | `POST` | Tombstone (soft-delete) a node |
| `/kg/edge/create` | `POST` | Create a directed edge |
| `/kg/edge/get` | `POST` | Retrieve edges by ID or filter |
| `/kg/edge/update` | `POST` | Redirect an old edge to a new one |
| `/kg/edge/delete` | `POST` | Tombstone an edge |
| `/kg/query` | `POST` | Semantic vector search over nodes |

---

## Graph Semantics

Kogwistar uses **non-destructive** semantics for all write operations:

- **Tombstone (delete)**: Marks a node/edge as `lifecycle_status: tombstoned`. The data is preserved but filtered from default queries.
- **Redirect (update)**: Links an old node/edge ID to a new version. Queries following the old ID transparently return the new one.

This ensures full audit trail and temporal traceability for all KG mutations.

---

## Verification

```bash
./scripts/demo-kg-crud.sh
```

All 7 steps should pass without errors:
1. ✅ Create Node 1 (OpenClaw)
2. ✅ Create Node 2 (Kogwistar)
3. ✅ Create Edge (Kogwistar powers OpenClaw)
4. ✅ Semantic query "open-source" returns both nodes
5. ✅ Get node by ID returns full metadata
6. ✅ Node redirect succeeds
7. ✅ Tombstoned node hidden from final query

---

## Pitfalls & Gotchas

See [pitfall.md](./pitfall.md) for lessons learned, including:
- Pydantic serialization conflicts (`field_mode="backend"` vs `mode="json"`)
- FastAPI `Body(embed=True)` for single-field JSON bodies
- Port 8788 conflict and how to resolve it
- Configuration caching in the OpenClaw plugin registry
