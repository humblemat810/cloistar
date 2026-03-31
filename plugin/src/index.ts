import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { KogwistarBridgeClient } from "./kogwistar-client.js";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import {
  type GovernanceApprovalResolution,
  buildAfterToolCallPayload,
  buildApprovalResolutionPayload,
  buildBeforeToolCallPayload,
  decisionToHookResult,
} from "./governance-contract.js";

type PluginConfig = {
  bridgeUrl: string;
  requestTimeoutMs?: number;
  defaultSeverity?: "info" | "warning" | "critical";
  logPayloads?: boolean;
};

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
      async (event, ctx) => {
        const payload = buildBeforeToolCallPayload(api.id, event, ctx);
        const decision = await client.evaluateBeforeToolCall(payload);

        return decisionToHookResult({
          decision,
          defaultSeverity: cfg.defaultSeverity,
          onResolution: async (resolution: GovernanceApprovalResolution) => {
            await client.emitApprovalResolution(
              buildApprovalResolutionPayload({
                pluginId: api.id,
                event,
                ctx,
                resolution,
                approvalId: decision.decision === "requireApproval" ? decision.approvalId ?? null : null,
              })
            );
          },
        });
      },
      { priority: 100 }
    );

    api.on("after_tool_call", async (event, ctx) => {
      await client.emitAfterToolCall(buildAfterToolCallPayload(api.id, event, ctx));
    });
  },
});
