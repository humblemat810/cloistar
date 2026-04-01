# OpenClaw Bridge E2E Status

This report captures what is currently proven about the OpenClaw -> plugin -> bridge integration in this repo, and what is still missing before we can claim a full end-to-end host session.

## What We Have Proven

The bridge and plugin contract are working together in a live local harness.

- The plugin builds and its contract helpers behave as expected in [plugin/test/governance-contract.test.js](/home/azureuser/cloistar/plugin/test/governance-contract.test.js#L63).
- The plugin sends `before_tool_call`, `after_tool_call`, and approval-resolution payloads to the bridge in the expected shape in [plugin/src/index.ts](/home/azureuser/cloistar/plugin/src/index.ts#L42) and [plugin/src/governance-contract.ts](/home/azureuser/cloistar/plugin/src/governance-contract.ts#L48).
- The bridge accepts those payloads and returns `allow`, `block`, and `requireApproval` decisions in [bridge/app/main.py](/home/azureuser/cloistar/bridge/app/main.py#L41).
- The bridge canonicalizes and stores approval resolution state in [bridge/app/integrations/openclaw_mapper.py](/home/azureuser/cloistar/bridge/app/integrations/openclaw_mapper.py#L160) and [bridge/app/main.py](/home/azureuser/cloistar/bridge/app/main.py#L73).
- The live harness proves the local plugin can talk to the live bridge and that the bridge records the expected event flow.

Confirmed live scenarios:

- `allow`: a safe `read` call produces observed, decision, and completed events.
- `block`: `exec` with `rm -rf /tmp/demo` is blocked by policy.
- `requireApproval` -> `allow-once`: the bridge records request, suspension, resolution, resume, and completion.
- `requireApproval` -> `deny`: the bridge records request, suspension, resolution, and denial.

## Evidence

Automated tests:

- `cd /home/azureuser/cloistar/plugin && npm test`
- `/home/azureuser/cloistar/.venv/bin/python -m pytest /home/azureuser/cloistar/bridge/tests`

Manual live smoke:

- `node /home/azureuser/cloistar/scripts/manual-governance-smoke.mjs`

The smoke run showed:

- plugin debug logs for `POST /policy/before-tool-call`, `POST /events/after-tool-call`, and `POST /approval/resolution`
- bridge logs for each HTTP request
- bridge state updates for observed, decision, approval requested, approval resolved, resumed, denied, and completed events

Relevant runtime contract evidence from OpenClaw upstream:

- Approval resolution values are `allow-once`, `allow-always`, `deny`, `timeout`, and `cancelled` in [openclaw/src/plugins/types.ts](/home/azureuser/cloistar/openclaw/src/plugins/types.ts#L2163).
- The hook docs say `onResolution` receives those same values in [openclaw/docs/automation/hooks.md](/home/azureuser/cloistar/openclaw/docs/automation/hooks.md#L499).

## What Is Still Missing

We have not yet proven a live OpenClaw host session end to end.

Missing pieces:

- A real OpenClaw gateway session that emits `before_tool_call` and `after_tool_call` from the host runtime.
- Host-level evidence that OpenClaw itself blocks a tool call when the plugin returns `block`.
- Host-level evidence that OpenClaw itself pauses for approval and then resumes after `allow-once` or `allow-always`.
- Live proof under a compatible OpenClaw runtime version. The local checked-out OpenClaw test/runtime stack did not run cleanly under Node `18.19.1`.

## Important Contract Notes

- The local plugin approval resolution type now matches the real OpenClaw vocabulary, not `approved`, in [plugin/src/governance-contract.ts](/home/azureuser/cloistar/plugin/src/governance-contract.ts#L3).
- The bridge stores approval resolutions internally as its canonical form, but the OpenClaw wire payload stays hyphenated, which is why the bridge DTO uses `allow-once` and related values in [bridge/app/integrations/openclaw_dto.py](/home/azureuser/cloistar/bridge/app/integrations/openclaw_dto.py#L31).

## Reproduction Steps

1. Start the bridge.

```bash
cd /home/azureuser/cloistar
docker compose -f docker-compose.dev.yml up --build bridge
```

2. Watch bridge logs.

```bash
docker compose -f docker-compose.dev.yml logs -f bridge
```

3. Run the local live smoke harness.

```bash
node /home/azureuser/cloistar/scripts/manual-governance-smoke.mjs
```

4. Inspect the final bridge state printed by the smoke script.

## Files Added For Validation

- [scripts/lib/openclaw-governance-harness.mjs](/home/azureuser/cloistar/scripts/lib/openclaw-governance-harness.mjs)
- [plugin/test/live-bridge.integration.test.js](/home/azureuser/cloistar/plugin/test/live-bridge.integration.test.js)
- [scripts/manual-governance-smoke.mjs](/home/azureuser/cloistar/scripts/manual-governance-smoke.mjs)

## Bottom Line

The plugin and bridge are working together correctly, and the bridge records the expected policy and approval state. What is not yet proven in this environment is a genuine OpenClaw host session where the gateway itself emits the hooks and enforces the returned decisions.
