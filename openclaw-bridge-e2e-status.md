# OpenClaw Bridge E2E Status

This report captures what is currently proven about the OpenClaw -> plugin -> bridge integration in this repo, and what is still missing before we can claim a full end-to-end host session.

For the fastest runnable setup on this repo, especially when you want to reverse-forward a local Ollama instance into a remote machine, use [openclaw-governance-e2e-quickstart.md](/home/azureuser/cloistar/openclaw-governance-e2e-quickstart.md).

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

## Kogwistar Reality Check

This repo does not yet contain a real durable Kogwistar backend integration in the active dev path.

What is real today:

- A real local OpenClaw checkout and plugin integration path.
- A real FastAPI bridge process that receives OpenClaw-shaped hook payloads over HTTP.
- Real bridge-side canonical event models and approval records.
- Real in-memory event capture and approval state transitions.

What is not yet real Kogwistar usage:

- No durable Kogwistar event append layer is wired in the active dev flow.
- No real projection or replay backend is wired in the active dev flow.
- No external Kogwistar service, database, or persistence boundary is being exercised.
- The current bridge policy is a local scaffold policy, not a proven production Kogwistar policy engine.

The repo’s own architecture doc says this directly: the current bridge is a "placeholder event sink" and "durable Kogwistar storage, projections, and replay layers are future integration targets" in [architecture.md](/home/azureuser/cloistar/architecture.md#L3).

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

Relevant local Kogwistar-scaffold evidence:

- The bridge title and description identify it as a "Thin governance bridge between OpenClaw hooks and Kogwistar" in [main.py](/home/azureuser/cloistar/bridge/app/main.py#L21).
- The bridge stores events and approvals only in an in-memory store in [store.py](/home/azureuser/cloistar/bridge/app/store.py#L11).
- The policy implementation is a simple local rule set based on dangerous tools and string markers in [policy.py](/home/azureuser/cloistar/bridge/app/policy.py#L13).
- The canonical governance event schema is present, but it is still local bridge-side modeling, not proof of a live Kogwistar backend, in [governance_models.py](/home/azureuser/cloistar/bridge/app/domain/governance_models.py#L32).

## What Is Still Missing

We have not yet proven a live OpenClaw host session end to end.

Missing pieces:

- A real OpenClaw gateway session that emits `before_tool_call` and `after_tool_call` from the host runtime.
- Host-level evidence that OpenClaw itself blocks a tool call when the plugin returns `block`.
- Host-level evidence that OpenClaw itself pauses for approval and then resumes after `allow-once` or `allow-always`.
- Live proof under the now-confirmed compatible OpenClaw runtime and provider setup. The original Node `18.19.1` concern was an environment-path mismatch in investigation, not the user’s actual interactive environment.

Separately, if the goal is "real Kogwistar usage" rather than "real OpenClaw host usage", we are also still missing:

- a real Kogwistar persistence layer
- a real Kogwistar projection or replay path
- a real external Kogwistar service boundary under load
- proof that bridge decisions come from real Kogwistar policy state instead of local scaffold rules

## Important Contract Notes

- The local plugin approval resolution type now matches the real OpenClaw vocabulary, not `approved`, in [plugin/src/governance-contract.ts](/home/azureuser/cloistar/plugin/src/governance-contract.ts#L3).
- The bridge stores approval resolutions internally as its canonical form, but the OpenClaw wire payload stays hyphenated, which is why the bridge DTO uses `allow-once` and related values in [bridge/app/integrations/openclaw_dto.py](/home/azureuser/cloistar/bridge/app/integrations/openclaw_dto.py#L31).

## Integration Rule

- Treat OpenClaw as an external immutable runtime dependency in this repo's bridge workflow.
- Use OpenClaw's documented runtime surfaces and compiled package entrypoints for integration.
- For live approval integration, prefer standard Gateway event subscription and operator APIs.
- Do not patch `openclaw/src` to surface approval ids or to make the bridge workflow function.
- Do not choose "probe by source patching OpenClaw" as an integration path. That is a bad design mistake for this repo because it couples the harness to a local fork instead of the real runtime boundary we are trying to validate.
- If approval visibility is missing, fix it at the bridge or harness boundary by subscribing to Gateway events, not by editing OpenClaw internals.

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

The plugin and bridge are working together correctly, and the bridge records the expected policy and approval state. But that bridge is still a Kogwistar-shaped scaffold, not a fully wired real Kogwistar backend. So the current repo status is:

- real OpenClaw checkout: yes
- real local plugin integration: yes
- real bridge HTTP/runtime path: yes
- real durable Kogwistar backend usage: no
- full live OpenClaw host-session proof: not yet complete
