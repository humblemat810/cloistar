# Dev Debug Cycle

This repo's development loop has three moving parts:

- OpenClaw runs on the host
- the `kogwistar-governance` plugin is built locally and loaded from the local `plugin/` path
- the FastAPI bridge runs in Docker via `docker-compose.dev.yml`

The plugin is the integration seam. OpenClaw emits hook events, the plugin turns them into HTTP calls, and the bridge returns the governance decision.

## Quick Loop

1. Start the bridge container.

```bash
./scripts/dev-up.sh
```

2. Build the plugin after editing `plugin/`.

```bash
cd plugin
npm run build
```

3. Re-register the local plugin and restart OpenClaw Gateway.

```bash
./scripts/install-plugin-host.sh
```

4. Watch the bridge logs while you exercise the flow.

```bash
docker compose -f docker-compose.dev.yml logs -f bridge
```

5. Stop the bridge when you are done.

```bash
./scripts/dev-down.sh
```

## What Changes Trigger What

| Change | What to do |
|--------|------------|
| `bridge/` code | Re-run `./scripts/dev-up.sh` or restart the bridge container |
| `plugin/` code | Re-run `npm run build`, then `./scripts/install-plugin-host.sh` |
| `configs/openclaw/openclaw.json5` | Restart OpenClaw Gateway |
| `.env` or bridge policy knobs | Restart the bridge container |

## How To Debug By Layer

### Bridge layer

- Confirm the container is up with `docker compose -f docker-compose.dev.yml ps`
- Check health with `curl http://127.0.0.1:8788/healthz`
- Inspect state with `curl http://127.0.0.1:8788/debug/state`
- Look for policy decisions and stored events in the bridge logs

### Plugin layer

- Rebuild the plugin after every source change
- Verify the OpenClaw plugin config still points at `http://127.0.0.1:8788`
- If tool calls are not reaching the bridge, check that OpenClaw was restarted after the plugin rebuild

### OpenClaw host layer

- Confirm the local plugin path in `configs/openclaw/openclaw.json5`
- Restart the gateway after any plugin or config change
- If OpenClaw is calling the plugin but not the bridge, the problem is usually in the plugin payload or the bridge URL in the OpenClaw config

## Common Failure Patterns

- Bridge starts but requests fail: check the bridge logs first, then confirm the bridge URL in the OpenClaw config and the local bridge address match.
- Plugin changes do nothing: rebuild `plugin/` and restart the OpenClaw Gateway.
- Tool call blocks unexpectedly: inspect the bridge decision logic and the `before_tool_call` payload in the bridge debug state.
- Approval never resolves: check that the plugin's approval callback is emitting `POST /approval/resolution`.

## Mental Model

Think of the loop as:

`OpenClaw host -> local plugin -> bridge container -> decision back to plugin -> OpenClaw host`

The bridge is the thing you usually inspect first when policy looks wrong, and the plugin is the thing you rebuild first when hook plumbing looks wrong.
