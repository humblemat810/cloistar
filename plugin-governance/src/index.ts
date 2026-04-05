import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import { GovernanceClient } from "./governance-client.js";
import {
  normalizeBeforeToolHook,
  normalizeAfterToolHook,
  normalizeApprovalResolution,
  toWirePayload,
  toDebugView,
  decisionToHookResult,
  type GovernanceApprovalResolution,
  type GovernanceSeverity,
} from "./governance-contract.js";

type PluginConfig = {
  bridgeUrl: string;
  requestTimeoutMs?: number;
  defaultSeverity?: GovernanceSeverity;
  logPayloads?: boolean;
};

export default definePluginEntry({
  id: "kogwistar-governance",
  name: "Kogwistar Governance",
  description:
    "Delegates OpenClaw tool governance decisions to a Kogwistar bridge",
  configSchema: {
    jsonSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        bridgeUrl: {
          type: "string",
          default: "http://127.0.0.1:8799",
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

    const client = new GovernanceClient({
      bridgeUrl: cfg.bridgeUrl ?? "http://127.0.0.1:8799",
      timeoutMs: cfg.requestTimeoutMs ?? 3000,
      logPayloads: cfg.logPayloads,
      logger: api.logger,
    });

    api.on(
      "before_tool_call",
      async (event: unknown, ctx: unknown) => {
        // Step 1: raw → normalized (canonical internal representation)
        const normalized = normalizeBeforeToolHook(event, ctx, api.id);

        // Step 2: project to wire and debug — two separate objects, derived
        // from the same normalized form. Never log the wire payload.
        const wirePayload = toWirePayload(normalized);
        const debugView = toDebugView(normalized);

        // Step 3: send wire to bridge, log debug
        const decision = await client.evaluateBeforeToolCall(
          wirePayload,
          debugView
        );

        // Step 4: convert bridge decision to OpenClaw hook result
        return decisionToHookResult({
          decision,
          defaultSeverity: cfg.defaultSeverity,
          onResolution: async (resolution: GovernanceApprovalResolution) => {
            // gatewayApprovalId: the approval ID from the bridge's requireApproval
            // response. This is bridge-side identity — never aliased to governanceCallId.
            const approvalId =
              decision.decision === "requireApproval"
                ? (decision.approvalId ?? null)
                : null;

            await client.emitApprovalResolution(
              normalizeApprovalResolution({
                normalized,
                resolution,
                approvalId,
              })
            );
          },
        });
      },
      { priority: 100 }
    );

    api.on("after_tool_call", async (event: unknown, ctx: unknown) => {
      const normalized = normalizeAfterToolHook(event, ctx, api.id);
      await client.emitAfterToolCall(normalized);
    });
  },
});
