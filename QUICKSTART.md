# Quickstart — Kogwistar × OpenClaw

This guide gets you from zero to a running Kogwistar bridge stack in three different ways:

1. **[Docker](#1-docker)** — fastest, zero Python setup required
2. **[Local Python (venv)](#2-local-python-venv)** — preferred for development
3. **[Using kogwistar as a Python library](#3-kogwistar-as-a-python-library)** — embed in your own project

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker (for option 1) | ≥ 24 | |
| Python (for options 2 & 3) | ≥ 3.12 | |
| Node.js (to build plugins) | ≥ 18 | Only needed if building TypeScript plugins |
| Ollama (optional embedding) | any | For local embedding & LLM calls |

---

## 1. Docker

The quickest path to a running local/self-hosted bridge.

### 1a. Clone and configure

```bash
git clone https://github.com/humblemat810/cloistar.git
cd cloistar
cp .env.example .env
```

Open `.env` and set the values relevant to your setup (the defaults work for a local Ollama + Chroma setup).

### 1b. Build and start the bridge

```bash
# Build from repo root (so kogwistar library is included in the image)
docker compose build

# Start the bridge
docker compose up -d
```

> **Note**: The default `docker-compose.yml` only starts the bridge on port **8799**.
> That bridge exposes both governance endpoints and `/kg/*` graph endpoints.
> For the full hardened stack (bridge + OpenClaw gateway + CLI), see [docker-compose.hardened.yml](./docker-compose.hardened.yml).

### 1c. Verify

```bash
curl http://localhost:8799/healthz
# → {"status":"ok"}

# Get all nodes (empty on a fresh start)
curl -s -X POST http://localhost:8799/kg/node/get \
  -H "Content-Type: application/json" \
  -d '{"limit": 5}'
# → {"ok":true,"nodes":[]}
```

### 1d. Stop

```bash
docker compose down
```

---

## 2. Local Python (venv)

Best experience for development and debugging.

### 2a. Clone the repo

```bash
git clone https://github.com/humblemat810/cloistar.git
cd cloistar
```

### 2b. Create and activate a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2c. Install the kogwistar library

```bash
pip install -e ./kogwistar[server]
```

### 2d. Install bridge dependencies

```bash
pip install -r bridge/requirements.txt
```

### 2e. Configure environment

```bash
cp .env.example .env
# Review and edit .env as needed
```

### 2f. Start the bridge

```bash
cd bridge
../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8799
```

Or from the repo root:

```bash
PYTHONPATH=. .venv/bin/python -m uvicorn bridge.app.main:app --host 0.0.0.0 --port 8799
```

### 2g. Verify

```bash
curl http://localhost:8799/healthz
```

---

## 3. Kogwistar as a Python Library

The `kogwistar` package can be used independently in your own Python project.

### 3a. Install from PyPI (once published)

```bash
pip install kogwistar
# With optional extras:
pip install "kogwistar[server]"      # FastAPI + uvicorn + fastmcp
pip install "kogwistar[chroma]"      # ChromaDB vector backend
pip install "kogwistar[pgvector]"    # Postgres + pgvector backend
pip install "kogwistar[openai]"      # OpenAI LLM integration
pip install "kogwistar[gemini]"      # Google Gemini LLM integration
pip install "kogwistar[ollama]"      # Ollama local LLM integration
pip install "kogwistar[full]"        # All optional extras
```

### 3b. Install from source (current)

```bash
git clone https://github.com/humblemat810/cloistar.git
cd cloistar
pip install -e ./kogwistar[server]
```

### 3c. Basic usage — graph operations

```python
from kogwistar.engine_core.models import Node, Edge, Span, Grounding

# Create a dummy grounding (required for all nodes/edges)
span = Span.from_dummy_for_conversation("my_context")
grounding = Grounding(spans=[span])

# Create a node
node = Node(
    label="Alice",
    type="entity",
    summary="A user in the system",
    mentions=[grounding],
)
print(node.id)  # auto-assigned UUID
```

### 3d. Calling the bridge from Python

```python
import httpx

bridge_url = "http://localhost:8799"

# Create a node via the bridge REST API
resp = httpx.post(f"{bridge_url}/kg/node/create", json={
    "label": "Alice",
    "type": "entity",
    "summary": "A user in the system",
})
print(resp.json())  # {"ok": true, "id": "..."}

# Query nodes semantically
resp = httpx.post(f"{bridge_url}/kg/query", json={
    "query": "user in the system",
    "n_results": 5,
})
print(resp.json())  # {"ok": true, "nodes": [...]}
```

---

## 4. Installing OpenClaw Plugins

The repo ships two OpenClaw plugins. These require a local OpenClaw installation.

- `plugin-governance/` handles tool-call governance hooks and approval callbacks
- `plugin-kg/` exposes bridge-backed Knowledge Graph CRUD and query tools

### 4a. Build plugins

```bash
# Governance plugin (before/after tool-call hooks + approval resolution)
cd plugin-governance
npm install
npm run build

# Knowledge Graph plugin (CRUD + query tools)
cd ../plugin-kg
npm install
npm run build
```

### 4b. Register with OpenClaw

```bash
# Register the governance plugin
openclaw extension add ./plugin-governance

# Register the KG plugin
openclaw extension add ./plugin-kg
```

### 4c. Configure bridge URL

In your OpenClaw config, set:

```json
{
  "kogwistar-governance": { "bridgeUrl": "http://127.0.0.1:8799" },
  "kogwistar-kg":         { "bridgeUrl": "http://127.0.0.1:8799" }
}
```

---

## 5. KG CRUD Quick Reference

Once the bridge is running and the `kogwistar-kg` plugin is installed:

| Operation | CLI | REST |
|---|---|---|
| **Create node** | `openclaw kg node create --label "Alice" --type entity --summary "A user"` | `POST /kg/node/create` |
| **Get node** | `openclaw kg node get --ids <id>` | `POST /kg/node/get` |
| **Semantic search** | `openclaw kg query "open source agent"` | `POST /kg/query` |
| **Redirect node** | `openclaw kg node update <old_id> <new_id>` | `POST /kg/node/update` |
| **Tombstone node** | `openclaw kg node delete <id>` | `POST /kg/node/delete` |
| **Create edge** | `openclaw kg edge create --relation "knows" --source-ids <id1> --target-ids <id2>` | `POST /kg/edge/create` |

---

## 6. Running the E2E Demo

```bash
# Full governance + KG end-to-end demo
./scripts/demo-kg-crud.sh

# Full OpenClaw governance demo
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b
```

---

## 7. Key Configuration Variables

| Variable | Default | Description |
|---|---|---|
| `BRIDGE_PORT` | `8799` | Port the bridge listens on |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` \| `openai` \| `gemini` |
| `EMBEDDING_MODEL` | `all-minilm:l6-v2` | Model used for vector search |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama server URL |
| `DANGEROUS_TOOLS` | `exec,apply_patch` | Tools always blocked |
| `BLOCK_PATTERNS` | `rm -rf,shutdown` | Command patterns to block |
| `APPROVAL_PATTERNS` | `delete,drop,truncate` | Command patterns needing approval |
| `OPENCLAW_APPROVAL_EVENT_SUBSCRIPTION` | `0` | Set to `1` to start approval listener |

See [`.env.example`](./.env.example) for the full list.

---

## 8. Troubleshooting

**Port conflict on 8788**
> Port 8788 is used by internal host-level processes. Always use **8799** for the bridge.

**`kogwistar` not found in bridge container**
> Make sure you `docker build` from the **repo root** (`docker compose build` from `cloistar/`), not from inside `bridge/`.

**Pydantic serialization errors**
> Use the installed `pydantic-extension` package from the venv. Do not rely on a repo-local shadow copy. See [pitfall.md](./pitfall.md).

**OpenClaw plugin config not updating**
> OpenClaw caches plugin configs. Run `openclaw extension reload <plugin-id>` after changing config.

---

## Next Steps

- [Architecture overview](./architecture.md)
- [KG integration guide](./kg_integration.md)
- [OpenClaw governance E2E quickstart](./openclaw-governance-e2e-quickstart.md)
- [Bridge E2E status](./openclaw-bridge-e2e-status.md)
- [Pitfalls & lessons learned](./pitfall.md)
