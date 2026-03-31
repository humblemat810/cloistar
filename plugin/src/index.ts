import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { KogwistarBridgeClient } from "./kogwistar-client.js";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";

type PluginConfig = {
  bridgeUrl: string;
  requestTimeoutMs?: number;
  defaultSeverity?: "info" | "warning" | "critical";
  logPayloads?: boolean;
};

function safeToolName(event: any): string | null {
  return event?.tool?.name ?? event?.toolName ?? event?.name ?? null;
}

function safeSessionId(event: any): string | null {
  return event?.session?.id ?? event?.sessionId ?? event?.context?.sessionId ?? null;
}

function safeParams(event: any): unknown {
  return event?.params ?? event?.arguments ?? event?.tool?.params ?? null;
}

export default definePluginEntry({
  id: "kogwistar-governance",
  name: "Kogwistar Governance",
  description: "Delegates OpenClaw tool governance decisions to a Kogwistar bridge",
  configSchema: {
    jsonSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        bridgeUrl: {
          type: "string",
          default: "http://127.0.0.1:8788",
        },
        requestTimeoutMs: {
          type: "number",
          default: 3000,
        },
        defaultSeverity: {
          anyOf: [
            { type: "string", const: "info" },
            { type: "string", const: "warning" },
            { type: "string", const: "critical" },
          ],
        },
        logPayloads: {
          type: "boolean",
          default: false,
        },
      },
    },
  },
  register(api: OpenClawPluginApi) {
    const cfg = (api.pluginConfig ?? {}) as PluginConfig;
    const client = new KogwistarBridgeClient({
      bridgeUrl: cfg.bridgeUrl ?? "http://127.0.0.1:8788",
      timeoutMs: cfg.requestTimeoutMs ?? 3000,
      logPayloads: cfg.logPayloads,
      logger: api.logger,
    });

    api.on(
      "before_tool_call",
      async (event: any) => {
        const payload = {
          pluginId: api.id,
          sessionId: safeSessionId(event),
          toolName: safeToolName(event),
          params: safeParams(event),
          rawEvent: event,
        };

        const decision = await client.evaluateBeforeToolCall(payload);

        if (decision.decision === "block") {
          return {
            block: true,
            blockReason: decision.reason,
          };
        }

        if (decision.decision === "requireApproval") {
          return {
            requireApproval: {
              title: decision.title,
              description: decision.description,
              severity: decision.severity ?? cfg.defaultSeverity ?? "warning",
              timeoutMs: decision.timeoutMs ?? 120000,
              timeoutBehavior: decision.timeoutBehavior ?? "deny",
              onResolution: async (resolution: string) => {
                await client.emitApprovalResolution({
                  pluginId: api.id,
                  sessionId: safeSessionId(event),
                  toolName: safeToolName(event),
                  resolution,
                  approvalId: (decision as any).approvalId ?? null,
                  rawEvent: event,
                });
              },
            },
          };
        }

        return {};
      },
      { priority: 100 }
    );

    api.on("after_tool_call", async (event: any) => {
      await client.emitAfterToolCall({
        pluginId: api.id,
        sessionId: safeSessionId(event),
        toolName: safeToolName(event),
        params: safeParams(event),
        result: event?.result ?? null,
        rawEvent: event,
      });
    });
  },
});
