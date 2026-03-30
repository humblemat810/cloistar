# Kogwistar × OpenClaw governance scaffold

This repo is a starter scaffold for a **thin OpenClaw plugin** plus a **local Kogwistar bridge service**.

The intent is to keep OpenClaw focused on execution while Kogwistar owns:

- policy evaluation
- event append / oplog intake
- approval state
- durable audit and projection

## Layout

```text
.
├── docker-compose.yml
├── .env.example
├── configs/
│   └── openclaw/
│       └── openclaw.json5
├── plugin/
│   ├── openclaw.plugin.json
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts
│       └── kogwistar-client.ts
├── bridge/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── models.py
│       ├── policy.py
│       └── store.py
└── scripts/
    ├── dev-up.sh
    ├── dev-down.sh
    └── install-plugin.sh
```

## What this scaffold does

- Runs a local FastAPI bridge on `http://127.0.0.1:8788`
- Ships an OpenClaw native plugin starter
- Intercepts `before_tool_call` and `after_tool_call`
- Sends tool-call proposals and outcomes to the bridge
- Lets the bridge decide:
  - allow
  - block
  - requireApproval

## What you still need to wire

This scaffold is intentionally thin. You still need to connect:

- real Kogwistar storage / event append
- real graph projection
- real approval persistence
- your exact OpenClaw local install path
- your preferred OpenClaw startup method

## Quick start

### 1) Start the bridge

```bash
cp .env.example .env
docker compose up --build bridge
```

### 2) Build the plugin

```bash
cd plugin
npm install
npm run build
```

### 3) Install the plugin into your local OpenClaw

From the repo root:

```bash
./scripts/install-plugin.sh
```

### 4) Point OpenClaw config at this plugin path

Copy the example config from:

```text
configs/openclaw/openclaw.json5
```

into your local OpenClaw config and update the absolute path placeholders.

### 5) Restart OpenClaw Gateway

```bash
openclaw gateway restart
```

## Development loop

- edit bridge code → `docker compose up --build bridge`
- edit plugin code → `npm run build`
- restart the gateway after plugin/config changes

## Suggested next steps

- replace the in-memory bridge store with your Kogwistar append API
- add a conversation binding adapter
- persist approval resolutions into your event log
- project tool calls into conversation / execution / governance graphs

## Hook architecture
OpenClaw runtime
   └─ asks hook: "may I do this tool call?"

Hook inside OpenClaw
   └─ asks external Kogwistar policy service

Kogwistar policy service
   └─ returns allow / block / requireApproval

Hook returns decision to OpenClaw
   └─ OpenClaw aborts, pauses, or continues