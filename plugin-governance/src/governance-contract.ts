/**
 * governance-contract.ts
 *
 * Protocol boundary between OpenClaw raw hook events and the Kogwistar bridge.
 *
 * Responsibilities:
 *   1. Parse raw upstream events into a canonical normalized form (internal mode)
 *   2. Project normalized events to wire payloads for the bridge
 *   3. Project normalized events to debug views for logging
 *   4. Convert bridge decisions to OpenClaw hook results
 *
 * What this file does NOT do:
 *   - Make governance decisions (the bridge does that)
 *   - Infer missing fields (absence is preserved, not filled)
 *   - Fabricate identities (governanceCallId = ctx.toolCallId ?? undefined)
 *   - Mix wire and debug shapes
 */

import {
  GovernanceCallSchema,
  GovernanceAfterCallSchema,
  ApprovalResolutionSchema,
  GovernanceDecisionSchema,
  RawBeforeToolHookSchema,
  RawAfterToolHookSchema,
  RawHookContextSchema,
  structuralSummary,
} from "./governance-schema.js";

// Re-export everything consumers need so they only import from this file.
export {
  GovernanceCallSchema,
  GovernanceAfterCallSchema,
  ApprovalResolutionSchema,
  GovernanceDecisionSchema,
  structuralSummary,
};

export type {
  // Canonical internal types
  NormalizedGovernanceCall,
  NormalizedAfterCall,
  NormalizedApprovalResolution,
  // Wire types (sent to bridge)
  GovernanceWirePayload,
  AfterCallWirePayload,
  ApprovalResolutionWire,
  // Debug types (safe to log)
  GovernanceDebugView,
  AfterCallDebugView,
  ApprovalResolutionDebug,
  // Bridge response
  GovernanceDecision,
} from "./governance-schema.js";

// ---------------------------------------------------------------------------
// Stable public literal types (stable across refactors)
// ---------------------------------------------------------------------------

export type GovernanceSeverity = "info" | "warning" | "critical";
export type GovernanceTimeoutBehavior = "allow" | "deny";
export type GovernanceApprovalResolution =
  | "allow-once"
  | "allow-always"
  | "deny"
  | "timeout"
  | "cancelled";

// ---------------------------------------------------------------------------
// ToolHookContext — structural mirror of OpenClaw hook ctx
// The SDK does not expose this on a stable import path yet.
// ---------------------------------------------------------------------------

export type ToolHookContext = {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  runId?: string;
  toolName: string;
  toolCallId?: string;
};

// ---------------------------------------------------------------------------
// Local observation counter
//
// NOT a governance identity. Does not represent a tool attempt.
// Used only to correlate debug log entries within a single plugin process.
// A new counter value is assigned per normalize() call.
// ---------------------------------------------------------------------------

const _processPrefix = Math.random().toString(36).slice(2, 6);
let _seq = 0;

function nextLocalObservationId(): string {
  return `obs-${_processPrefix}-${++_seq}`;
}

// ---------------------------------------------------------------------------
// Normalizers — raw → internal (canonical)
//
// These are the ONLY functions that touch raw upstream data.
// After normalization, all further operations work on NormalizedGovernanceCall
// or NormalizedAfterCall. Raw events are never passed further.
// ---------------------------------------------------------------------------

import type {
  NormalizedGovernanceCall,
  NormalizedAfterCall,
  NormalizedApprovalResolution,
  GovernanceWirePayload,
  AfterCallWirePayload,
  ApprovalResolutionWire,
  GovernanceDebugView,
  AfterCallDebugView,
  GovernanceDecision,
} from "./governance-schema.js";

export function normalizeBeforeToolHook(
  rawEvent: unknown,
  rawCtx: unknown,
  pluginId: string
): NormalizedGovernanceCall {
  const event = RawBeforeToolHookSchema.parse(rawEvent);
  const ctx = RawHookContextSchema.parse(rawCtx);

  // Identity invariant: toolCallId MUST be present. Absent id → error.
  // We never fabricate a call identity and we never silently proceed without
  // one. This is a strict requirement for replay stability.
  if (!ctx.toolCallId) {
    throw new Error(
      `[kogwistar-governance] governanceCallId cannot be established: ctx.toolCallId is absent. ` +
      `OpenClaw must provide a stable toolCallId for every tool-call hook. ` +
      `Tool: ${ctx.toolName ?? "unknown"}`
    );
  }

  return {
    governanceCallId: ctx.toolCallId,
    localObservationId: nextLocalObservationId(),
    pluginId,
    sessionId: ctx.sessionId ?? ctx.sessionKey ?? null,
    toolName: event.toolName ?? ctx.toolName ?? null,
    params: event.params,
    paramsSummary: structuralSummary(event.params),
  };
}

export function normalizeAfterToolHook(
  rawEvent: unknown,
  rawCtx: unknown,
  pluginId: string
): NormalizedAfterCall {
  const event = RawAfterToolHookSchema.parse(rawEvent);
  const ctx = RawHookContextSchema.parse(rawCtx);

  // Same identity invariant as normalizeBeforeToolHook.
  if (!ctx.toolCallId) {
    throw new Error(
      `[kogwistar-governance] governanceCallId cannot be established: ctx.toolCallId is absent in after_tool_call hook. ` +
      `Tool: ${ctx.toolName ?? "unknown"}`
    );
  }

  // Distinguish "result was reported" from "result was absent".
  // Do NOT default to null. `after_tool_call` firing does not mean completion.
  const resultPresent = "result" in (event as Record<string, unknown>);

  return {
    governanceCallId: ctx.toolCallId,
    localObservationId: nextLocalObservationId(),
    pluginId,
    sessionId: ctx.sessionId ?? ctx.sessionKey ?? null,
    toolName: event.toolName ?? ctx.toolName ?? null,
    params: event.params,
    paramsSummary: structuralSummary(event.params),
    result: resultPresent ? event.result : undefined,
    resultSummary: resultPresent ? structuralSummary(event.result) : undefined,
    error: event.error,
    durationMs: event.durationMs,
  };
}

export function normalizeApprovalResolution(args: {
  normalized: NormalizedGovernanceCall;
  resolution: GovernanceApprovalResolution;
  /**
   * The approval request ID returned by the bridge in the requireApproval decision.
   * Named `approvalId` to match the bridge DTO field (`OpenClawApprovalResolutionPayload.approvalId`).
   * This is a BRIDGE-SIDE identity — distinct from governanceCallId.
   * Null if the bridge did not return one.
   */
  approvalId: string | null;
}): NormalizedApprovalResolution {
  return {
    pluginId: args.normalized.pluginId,
    sessionId: args.normalized.sessionId,
    toolName: args.normalized.toolName,
    resolution: args.resolution,
    // Carry the original per-attempt identity (NOT sent on wire — bridge fetches it from its stored approval).
    governanceCallId: args.normalized.governanceCallId,
    // Bridge-side approval request ID — separate from governanceCallId, never aliased.
    approvalId: args.approvalId,
  };
}

// ---------------------------------------------------------------------------
// Projection helpers — internal → wire | debug
//
// These are the ONLY way to produce a wire or debug object.
// Never spread a normalized object manually. Never log a wire payload.
// ---------------------------------------------------------------------------

export function toWirePayload(
  normalized: NormalizedGovernanceCall
): GovernanceWirePayload {
  return GovernanceCallSchema.dump(normalized, "wire") as GovernanceWirePayload;
}

export function toDebugView(
  normalized: NormalizedGovernanceCall
): GovernanceDebugView {
  return GovernanceCallSchema.dump(normalized, "debug") as GovernanceDebugView;
}

export function toAfterCallWirePayload(
  normalized: NormalizedAfterCall
): AfterCallWirePayload {
  return GovernanceAfterCallSchema.dump(
    normalized,
    "wire"
  ) as AfterCallWirePayload;
}

export function toAfterCallDebugView(normalized: NormalizedAfterCall): AfterCallDebugView {
  return GovernanceAfterCallSchema.dump(
    normalized,
    "debug"
  ) as AfterCallDebugView;
}

export function toApprovalWire(
  normalized: NormalizedApprovalResolution
): ApprovalResolutionWire {
  return ApprovalResolutionSchema.dump(
    normalized,
    "wire"
  ) as ApprovalResolutionWire;
}

export function parseGovernanceDecision(raw: unknown): GovernanceDecision {
  return GovernanceDecisionSchema.parse(raw);
}

// ---------------------------------------------------------------------------
// HookDecisionResult — the shape OpenClaw expects back from before_tool_call
// ---------------------------------------------------------------------------

export type HookDecisionResult =
  | Record<string, never>
  | { block: true; blockReason: string }
  | {
      requireApproval: {
        title: string;
        description: string;
        severity: GovernanceSeverity;
        timeoutMs: number;
        timeoutBehavior: GovernanceTimeoutBehavior;
        onResolution: (
          resolution: GovernanceApprovalResolution
        ) => Promise<void>;
      };
    };

export function decisionToHookResult(args: {
  decision: GovernanceDecision;
  defaultSeverity?: GovernanceSeverity;
  onResolution: (resolution: GovernanceApprovalResolution) => Promise<void>;
}): HookDecisionResult {
  const { decision, defaultSeverity, onResolution } = args;

  if (decision.decision === "allow") {
    return {};
  }

  if (decision.decision === "block") {
    return {
      block: true,
      blockReason: decision.reason,
    };
  }

  return {
    requireApproval: {
      title: decision.title,
      description: decision.description,
      severity: decision.severity ?? defaultSeverity ?? "warning",
      timeoutMs: decision.timeoutMs ?? 120000,
      timeoutBehavior: decision.timeoutBehavior ?? "deny",
      onResolution,
    },
  };
}
