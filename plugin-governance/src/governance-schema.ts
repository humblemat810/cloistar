import { expedition, type InferMode } from "titanic-expedition";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Structural summary helper — debug observability without data leakage
// ---------------------------------------------------------------------------

export function structuralSummary(value: unknown): string {
  if (value === undefined) return "[undefined]";
  if (value === null) return "[null]";
  if (Array.isArray(value)) return `[array: ${value.length} items]`;
  if (typeof value === "object")
    return `[object: ${Object.keys(value as Record<string, unknown>).length} keys]`;
  if (typeof value === "string") return `[string: ${value.length} chars]`;
  if (typeof value === "number") return "[number]";
  if (typeof value === "boolean") return "[boolean]";
  return `[${typeof value}]`;
}

// ---------------------------------------------------------------------------
// Raw hook event schemas — Zod only, untrusted input gate
// Passthrough so unexpected upstream fields are preserved for diagnosis.
// ---------------------------------------------------------------------------

export const RawBeforeToolHookSchema = z
  .object({
    toolName: z.string().optional(),
    params: z.unknown().optional(),
    runId: z.string().optional(),
    toolCallId: z.string().optional(),
  })
  .passthrough();

export const RawAfterToolHookSchema = RawBeforeToolHookSchema.extend({
  result: z.unknown().optional(),
  error: z.string().optional(),
  durationMs: z.number().optional(),
});

export const RawHookContextSchema = z
  .object({
    agentId: z.string().optional(),
    sessionKey: z.string().optional(),
    sessionId: z.string().optional(),
    runId: z.string().optional(),
    toolName: z.string().optional(),
    toolCallId: z.string().optional(),
  })
  .passthrough();

export type RawBeforeToolHook = z.infer<typeof RawBeforeToolHookSchema>;
export type RawAfterToolHook = z.infer<typeof RawAfterToolHookSchema>;
export type RawHookContext = z.infer<typeof RawHookContextSchema>;

// ---------------------------------------------------------------------------
// GovernanceCallSchema
//
// One schema family — three modes:
//
//   internal  canonical normalized event (full truth inside plugin)
//   wire      exact payload sent to bridge (no debug/internal fields)
//   debug     safe to log (no raw params, structural summaries instead)
//
// Mode field assignments follow strict boundary rules:
//   params        → internal + wire         (bridge needs it; never logged raw)
//   paramsSummary → internal + debug        (logged; never sent to bridge)
//   localObsId    → internal + debug        (correlation only; never on wire)
//   sessionId     → internal + wire + debug (identity across all views)
//   toolName      → internal + wire + debug (identity across all views)
//   governanceCallId → all three            (carried, never fabricated)
// ---------------------------------------------------------------------------

export const GovernanceCallSchema = expedition.object({
  /**
   * Per-attempt identity. Carried from ctx.toolCallId.
   *
   * REQUIRED. If toolCallId is absent upstream the normalizer THROWS — it is
   * never defaulted, never fabricated, never set to undefined.
   *
   * NOT on wire: the bridge rejects it (extra_forbidden, additionalProperties:
   * false). Kept in internal + debug for plugin-side correlation only.
   */
  governanceCallId: expedition
    .string()
    .modes(["internal", "debug"]),

  /**
   * Plugin-local observation counter. NOT a governance identity.
   * Used to correlate debug log entries within a single plugin process.
   * Must never appear on the wire — it is meaningless to the bridge.
   */
  localObservationId: expedition.string().modes(["internal", "debug"]),

  pluginId: expedition.string().modes(["internal", "wire", "debug"]),

  /**
   * Null when absent upstream. Never defaulted to a synthetic value.
   */
  sessionId: expedition.string().modes(["internal", "wire", "debug"]).nullable(),

  /**
   * Null when absent in both event and ctx. Never defaulted.
   */
  toolName: expedition.string().modes(["internal", "wire", "debug"]).nullable(),

  /**
   * Actual params — bridge needs this for policy evaluation.
   * Never logged raw; use paramsSummary for observability.
   */
  params: expedition.unknown().modes(["internal", "wire"]).optional(),

  /**
   * Structural summary of params for debug logging.
   * Shape-level signal only. No sensitive field values.
   */
  paramsSummary: expedition.string().modes(["internal", "debug"]),
});

export type NormalizedGovernanceCall = InferMode<
  typeof GovernanceCallSchema,
  "internal"
>;
export type GovernanceWirePayload = InferMode<
  typeof GovernanceCallSchema,
  "wire"
>;
export type GovernanceDebugView = InferMode<
  typeof GovernanceCallSchema,
  "debug"
>;

// ---------------------------------------------------------------------------
// GovernanceAfterCallSchema
//
// Extends the before-call shape with result, error, and duration.
// result is explicitly optional: absent ≠ success. Model the ambiguity.
// ---------------------------------------------------------------------------

export const GovernanceAfterCallSchema = expedition.object({
  /**
   * Same enforcement as GovernanceCallSchema.governanceCallId.
   * REQUIRED. Normalizer throws if absent. NOT on wire.
   */
  governanceCallId: expedition
    .string()
    .modes(["internal", "debug"]),

  localObservationId: expedition.string().modes(["internal", "debug"]),

  pluginId: expedition.string().modes(["internal", "wire", "debug"]),

  sessionId: expedition
    .string()
    .modes(["internal", "wire", "debug"])
    .nullable(),

  toolName: expedition.string().modes(["internal", "wire", "debug"]).nullable(),

  params: expedition.unknown().modes(["internal", "wire"]).optional(),
  paramsSummary: expedition.string().modes(["internal", "debug"]),

  /**
   * Execution result — optional. Absent means the result was not reported,
   * NOT that execution succeeded. Do not default to null.
   */
  result: expedition.unknown().modes(["internal", "wire"]).optional(),

  /**
   * Structural summary of result for debug. Optional: absent when result
   * was not reported.
   */
  resultSummary: expedition.string().modes(["internal", "debug"]).optional(),

  /**
   * Error string — absent means no error was reported, not that there
   * was no error. Preserve ambiguity.
   */
  error: expedition.string().modes(["internal", "wire", "debug"]).optional(),

  /**
   * Duration for observability. Never on wire — the bridge tracks its own
   * timing.
   */
  durationMs: expedition.number().modes(["internal", "debug"]).optional(),
});

export type NormalizedAfterCall = InferMode<
  typeof GovernanceAfterCallSchema,
  "internal"
>;
export type AfterCallWirePayload = InferMode<
  typeof GovernanceAfterCallSchema,
  "wire"
>;
export type AfterCallDebugView = InferMode<
  typeof GovernanceAfterCallSchema,
  "debug"
>;

// ---------------------------------------------------------------------------
// ApprovalResolutionSchema
//
// Identity discipline:
//   governanceCallId  — from the original before-hook, carried unchanged
//   gatewayApprovalId — assigned BY THE BRIDGE in its requireApproval response
//
// These are DIFFERENT identities. Never alias them. Never merge them.
// gatewayApprovalId is nullable: the bridge may not return one.
// ---------------------------------------------------------------------------

export const ApprovalResolutionSchema = expedition.object({
  pluginId: expedition.string().modes(["internal", "wire", "debug"]),

  sessionId: expedition
    .string()
    .modes(["internal", "wire", "debug"])
    .nullable(),

  toolName: expedition.string().modes(["internal", "wire", "debug"]).nullable(),

  resolution: expedition
    .enum(["allow-once", "allow-always", "deny", "timeout", "cancelled"])
    .modes(["internal", "wire", "debug"]),

  /**
   * The per-attempt identity from the original before-hook.
   * REQUIRED here (normalizer throws on absent toolCallId).
   * NOT on wire: the bridge resolution endpoint does not accept it
   * (extra_forbidden). The bridge fetches governanceCallId from its own
   * stored approval record using approvalId as the lookup key.
   */
  governanceCallId: expedition
    .string()
    .modes(["internal", "debug"]),

  /**
   * The approval request ID assigned by the bridge in its requireApproval
   * response. Field name is `approvalId` to match the bridge DTO field
   * (`OpenClawApprovalResolutionPayload.approvalId`).
   *
   * This is a BRIDGE-SIDE identity — distinct from governanceCallId.
   * Null if the bridge did not return one.
   */
  approvalId: expedition
    .string()
    .modes(["internal", "wire", "debug"])
    .nullable(),
});

export type NormalizedApprovalResolution = InferMode<
  typeof ApprovalResolutionSchema,
  "internal"
>;
export type ApprovalResolutionWire = InferMode<
  typeof ApprovalResolutionSchema,
  "wire"
>;
export type ApprovalResolutionDebug = InferMode<
  typeof ApprovalResolutionSchema,
  "debug"
>;

// ---------------------------------------------------------------------------
// GovernanceDecisionSchema — validated response from bridge
//
// Parsed with Zod (not expedition) because this is incoming data, not a
// projection. We validate it so any malformed bridge response is caught
// at the boundary.
// ---------------------------------------------------------------------------

export const GovernanceDecisionSchema = z.discriminatedUnion("decision", [
  z.object({
    decision: z.literal("allow"),
    annotations: z.record(z.string(), z.unknown()).optional(),
  }),
  z.object({
    decision: z.literal("block"),
    reason: z.string(),
  }),
  z.object({
    decision: z.literal("requireApproval"),
    title: z.string(),
    description: z.string(),
    severity: z.enum(["info", "warning", "critical"]).optional(),
    timeoutMs: z.number().optional(),
    timeoutBehavior: z.enum(["allow", "deny"]).optional(),
    /**
     * The approval ID assigned by the bridge for this approval request.
     * This is NOT the same as a governanceCallId from the hook event.
     * It is the bridge's own handle for this pending approval.
     */
    approvalId: z.string().optional(),
  }),
]);

export type GovernanceDecision = z.infer<typeof GovernanceDecisionSchema>;
