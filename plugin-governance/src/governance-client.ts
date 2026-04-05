import { type BridgeLogger } from "./bridge-transport.js";
import { BridgeTransport } from "./bridge-transport.js";
import {
  parseGovernanceDecision,
  toAfterCallWirePayload,
  toAfterCallDebugView,
  toApprovalWire,
} from "./governance-contract.js";
import type {
  GovernanceDecision,
  GovernanceWirePayload,
  NormalizedAfterCall,
  NormalizedApprovalResolution,
} from "./governance-contract.js";

type GovernanceClientOptions = {
  bridgeUrl: string;
  timeoutMs: number;
  logPayloads?: boolean;
  logger?: BridgeLogger;
};

/**
 * Governance-only client for the Kogwistar bridge.
 *
 * Responsibilities:
 *   - Send wire payloads to governance endpoints
 *   - Validate bridge responses
 *   - Log debug projections (never wire payloads)
 *
 * Does NOT handle KG operations. Those belong in plugin-kg.
 */
export class GovernanceClient {
  private readonly transport: BridgeTransport;
  private readonly logPayloads: boolean;
  private readonly logger: BridgeLogger | undefined;

  constructor(opts: GovernanceClientOptions) {
    this.transport = new BridgeTransport({
      bridgeUrl: opts.bridgeUrl,
      timeoutMs: opts.timeoutMs,
      logger: opts.logger,
    });
    this.logPayloads = Boolean(opts.logPayloads);
    this.logger = opts.logger;
  }

  private log(path: string, debugView: unknown): void {
    if (this.logPayloads) {
      // Always log the debug projection — never the wire payload.
      this.logger?.debug?.(
        `[kogwistar] POST ${path} ${JSON.stringify(debugView)}`
      );
    }
  }

  /**
   * Evaluate a before-tool-call event.
   *
   * Caller is responsible for producing wirePayload and debugView from the
   * same NormalizedGovernanceCall via toWirePayload() and toDebugView().
   * They must never be the same object.
   */
  async evaluateBeforeToolCall(
    wirePayload: GovernanceWirePayload,
    debugView: unknown
  ): Promise<GovernanceDecision> {
    const path = "/policy/before-tool-call";
    this.log(path, debugView);
    const raw = await this.transport.post<unknown>(path, wirePayload);
    // Validate the bridge response at the boundary.
    return parseGovernanceDecision(raw);
  }

  async emitAfterToolCall(normalized: NormalizedAfterCall): Promise<{ ok: true }> {
    const path = "/events/after-tool-call";
    const wirePayload = toAfterCallWirePayload(normalized);
    const debugView = toAfterCallDebugView(normalized);
    this.log(path, debugView);
    return this.transport.post<{ ok: true }>(path, wirePayload);
  }

  async emitApprovalResolution(
    normalized: NormalizedApprovalResolution
  ): Promise<{ ok: true }> {
    const path = "/approval/resolution";
    const wirePayload = toApprovalWire(normalized);
    // ApprovalResolutionDebug and wire share the same fields (no sensitive data
    // in this payload), but we still use the schema dump so mode enforcement
    // is explicit and consistent.
    this.log(path, wirePayload);
    return this.transport.post<{ ok: true }>(path, wirePayload);
  }
}
