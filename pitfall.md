# Pitfall Manifest - Kogwistar KG CRUD Integration

This document catalog the technical hurdles, "gotchas," and architectural lessons encountered during the implementation of the Kogwistar Knowledge Graph CRUD tools.

## 1. Port 8788 Conflict (The "Ghost" Process)
> [!CAUTION]
> **Issue**: The default `8788` port for the Kogwistar bridge was intermittently blocked or returned `404` despite the bridge process appearing healthy.
> 
> **Finding**: A root-level process on the host was already bound to `8788`. This caused requests from the OpenClaw CLI to be routed to the wrong handler or fail silently.
> 
> **Resolution**: Switched the bridge and plugin configuration to port **8799**. Always verify port availability with `lsof -i :<port>` if 404s appear on a known route.

## 2. Configuration Caching (The "Stale Config" Trap)
> [!IMPORTANT]
> **Issue**: Changes to `configSchema` defaults in `index.ts` (e.g., updating the port) were not reflected when running the OpenClaw CLI.
> 
> **Finding**: OpenClaw caches the *resolved* configuration for installed plugins in `[openclaw-config-dir]/openclaw.json`. Even if the plugin source code changes, the existing `config` object in the entry takes precedence over the code's new defaults.
> 
> **Resolution**: 
> 1. Use `plugins.load.paths` for active development to force re-discovery.
> 2. Manually clear state from `[openclaw-config-dir]/openclaw.json` or use `plugins uninstall` / `plugins install`.
> 3. Verify the current "live" config with `openclaw config get plugins.entries.<id> --json`.

## 3. Log Swallowing in CLI Context
> [!WARNING]
> **Issue**: `console.log` statements in plugin CLI actions were not appearing in the terminal.
> 
> **Finding**: When shell variables are assigned via command substitution (e.g., `RESULT=$(openclaw kg ...)`) or when the CLI is piped, `stdout` might be captured or buffered in ways that hide standard logs.
> 
> **Resolution**: Use `process.stderr.write()` for diagnostic logs and critical error messages in plugin code. This ensure they bypass standard capture and appear in the user's terminal.

## 4. Duplicate Plugin ID Conflicts
> [!NOTE]
> **Issue**: "Duplicate plugin ID detected" warnings in the CLI output.
> 
> **Finding**: Having a plugin in `plugins.load.paths` *and* an explicit `plugins.installs` entry with the same ID causes a conflict where the global/stock plugin is overridden.
> 
> **Resolution**: For local development, remove the duplicate entry from `plugins.installs` and rely on `load.paths`. Avoid using `npm` package names as IDs if they differ from the `definePluginEntry` manifest ID.

## 5. Mandatory Grounding for Primitive Engines
> [!TIP]
> **Issue**: Engines like Kogwistar often enforce strict "mentions" or "grounding" data (spans, source IDs) for node and edge creation.
> 
> **Finding**: Creating nodes via a CLI tool often lacks the natural conversational context (spans) that the engine expects.
> 
> **Resolution**: Use `Span.from_dummy_for_conversation("manual_crud")` in the bridge layer to satisfy engine constraints while maintaining traceability for manual edits.
