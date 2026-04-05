export type GovernanceSeverity = "info" | "warning" | "critical";
export type GovernanceTimeoutBehavior = "allow" | "deny";
export type GovernanceApprovalResolution =
  | "allow-once"
  | "allow-always"
  | "deny"
  | "timeout"
  | "cancelled";

// Mirrors the current OpenClaw tool hook payloads. The SDK does not expose
// these hook event types on a stable public import path yet, so we keep the
// contract structural and local here.
export type ToolHookContext = {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  runId?: string;
  toolName: string;
  toolCallId?: string;
};

export type BeforeToolHookEvent = {
  toolName: string;
  params: Record<string, unknown>;
  runId?: string;
  toolCallId?: string;
};

export type AfterToolHookEvent = BeforeToolHookEvent & {
  result?: unknown;
  error?: string;
  durationMs?: number;
};

export type GovernanceDecision =
  | { decision: "allow"; annotations?: Record<string, unknown> }
  | { decision: "block"; reason: string }
  | {
      decision: "requireApproval";
      title: string;
      description: string;
      severity?: GovernanceSeverity;
      timeoutMs?: number;
      timeoutBehavior?: GovernanceTimeoutBehavior;
      approvalId?: string;
    };

export type BeforeToolCallPayload = {
  pluginId: string;
  sessionId?: string | null;
  toolName?: string | null;
  params?: unknown;
  rawEvent: unknown;
};

export type AfterToolCallPayload = {
  pluginId: string;
  sessionId?: string | null;
  toolName?: string | null;
  params?: unknown;
  result?: unknown;
  rawEvent: unknown;
};

export type ApprovalResolutionPayload = {
  pluginId: string;
  sessionId?: string | null;
  toolName?: string | null;
  resolution: GovernanceApprovalResolution;
  approvalId?: string | null;
  rawEvent: unknown;
};

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
      onResolution: (resolution: GovernanceApprovalResolution) => Promise<void>;
    };
  };

export function buildBeforeToolCallPayload(
  pluginId: string,
  event: BeforeToolHookEvent,
  ctx: ToolHookContext
): BeforeToolCallPayload {
  return {
    pluginId,
    sessionId: ctx.sessionId ?? ctx.sessionKey ?? null,
    toolName: event.toolName ?? ctx.toolName ?? null,
    params: event.params,
    rawEvent: event,
  };
}

export function buildAfterToolCallPayload(
  pluginId: string,
  event: AfterToolHookEvent,
  ctx: ToolHookContext
): AfterToolCallPayload {
  return {
    pluginId,
    sessionId: ctx.sessionId ?? ctx.sessionKey ?? null,
    toolName: event.toolName ?? ctx.toolName ?? null,
    params: event.params,
    result: event.result ?? null,
    rawEvent: event,
  };
}

export function buildApprovalResolutionPayload(args: {
  pluginId: string;
  event: BeforeToolHookEvent;
  ctx: ToolHookContext;
  resolution: GovernanceApprovalResolution;
  approvalId?: string | null;
}): ApprovalResolutionPayload {
  return {
    pluginId: args.pluginId,
    sessionId: args.ctx.sessionId ?? args.ctx.sessionKey ?? null,
    toolName: args.event.toolName ?? args.ctx.toolName ?? null,
    resolution: args.resolution,
    approvalId: args.approvalId ?? null,
    rawEvent: args.event,
  };
}

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
