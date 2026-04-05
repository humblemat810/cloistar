# Pitfall Manifest - Kogwistar KG CRUD Integration

This document catalogs technical hurdles, "gotchas," and architectural lessons encountered during the implementation of the Kogwistar Knowledge Graph CRUD tools.

## 1. Port 8788 Conflict (The "Ghost" Process)
> [!CAUTION]
> **Issue**: The default `8788` port for the Kogwistar bridge was intermittently blocked or returned `404` despite the bridge process appearing healthy.
> 
> **Finding**: A root-level process on the host was already bound to `8788`. This caused requests from the OpenClaw CLI to be routed to the wrong handler or fail silently.
> 
> **Resolution**: Switched the bridge and plugin configuration to port **8799**. Always verify port availability with `fuser -k <port>/tcp` or `lsof -i :<port>` if 404s appear.

## 2. Configuration Caching (The "Stale Config" Trap)
> [!IMPORTANT]
> **Issue**: Changes to `configSchema` defaults in `index.ts` (e.g., updating the port) were not reflected when running the OpenClaw CLI.
> 
> **Finding**: OpenClaw caches the *resolved* configuration for installed plugins in its global config (e.g., `~/.openclaw/openclaw.json`). Even if the plugin source code changes, the existing `config` object in the entry takes precedence over the code's new defaults.
> 
> **Resolution**: 
> 1. Use `plugins.load.paths` for active development to force re-discovery.
> 2. Manually clear state from the global config or use `openclaw plugins uninstall` / `install`.

## 3. Log Swallowing in CLI Context
> [!WARNING]
> **Issue**: `console.log` statements in plugin CLI actions were not appearing in the terminal when captured by scripts.
> 
> **Finding**: When shell variables are assigned via command substitution (e.g., `RESULT=$(openclaw kg ...)`), `stdout` is captured by the shell. Diagnostic logs on `stdout` will pollute the captured variable and not appear in the terminal.
> 
> **Resolution**: Use `process.stderr.write()` for diagnostic logs and `process.stdout.write()` (or `console.log`) *only* for the final machine-readable result (e.g., JSON).

## 4. Pydantic Serialization Conflict
> [!NOTE]
> **Issue**: `TypeError: ... got multiple values for keyword argument 'mode'` when calling `model_dump(mode="json")`.
> 
> **Finding**: Modern Pydantic (v2) uses `mode="json"`, but custom mixins (like Kogwistar's `ModeSlicingMixin`) may override `model_dump` and use different arguments like `field_mode`.
> 
> **Resolution**: Use the engine-specific serialization mode (e.g., `model_dump(field_mode="backend")`) to ensure compatibility with custom base models and extension mixins.

## 5. FastAPI Body vs Query Parameters
> [!TIP]
> **Issue**: `422 Unprocessable Entity` when sending a JSON body for `DELETE` or `GET` operations.
> 
> **Finding**: FastAPI defaults single-field parameters (like `node_id: str`) to URL query parameters unless explicitly marked with `Body()`. If the client sends `{ "node_id": "..." }` in the JSON body, FastAPI will fail to find it.
> 
> **Resolution**: 
> 1. Use a Pydantic model for the request body.
> 2. Or use `node_id: str = Body(..., embed=True)` to tell FastAPI to look for an embedded key in the JSON body.

## 6. Mandatory Grounding for Manual CRUD
> [!NOTE]
> **Issue**: Creating nodes/edges via CLI often lacks the natural conversational source that automated engines expect.
> 
> **Finding**: Engines like Kogwistar may enforce strict "mentions" or "grounding" data (spans, source IDs) for node and edge creation to maintain traceability.
> 
> **Resolution**: Inject dummy grounding metadata (e.g., `doc_id="conversation/_conv:manual_crud"`) in the bridge layer to satisfy engine constraints while distinguishing manual edits from automated ones.
