/**
 * Minimal ambient declarations for the openclaw plugin SDK.
 *
 * The openclaw package ships as plain JS without bundled TypeScript
 * declarations. This file provides the structural types this plugin
 * needs so the compiler can type-check our usage without requiring an
 * upstream @types/openclaw package.
 *
 * If openclaw ever publishes official declarations, delete this file
 * and let module resolution find the real ones.
 */
declare module "openclaw/plugin-sdk/plugin-entry" {
  export type PluginLogger = {
    debug?: (msg: string) => void;
    info?: (msg: string) => void;
    warn?: (msg: string) => void;
    error?: (msg: string) => void;
  };

  export type OpenClawPluginApi = {
    /** The plugin's registered id. */
    id: string;
    /** Raw config object as supplied by the user's openclaw.json. */
    pluginConfig: unknown;
    /** Structured logger provided by the runtime. */
    logger: PluginLogger;
    /** Register a hook handler for a named lifecycle event. */
    on(
      event: string,
      handler: (event: unknown, ctx: unknown) => unknown,
      options?: { priority?: number }
    ): void;
    /** Register a tool callable by the AI agent. */
    registerTool(spec: unknown): void;
    /** Register CLI sub-commands under the plugin namespace. */
    registerCli(
      factory: (ctx: { program: unknown }) => void,
      options?: unknown
    ): void;
  };

  export function definePluginEntry(spec: {
    id: string;
    name: string;
    description: string;
    configSchema?: unknown;
    register(api: OpenClawPluginApi): void;
  }): unknown;
}
