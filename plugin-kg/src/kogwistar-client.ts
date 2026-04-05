import { BridgeTransport, type BridgeLogger } from "./bridge-transport.js";

type KgClientOptions = {
  bridgeUrl: string;
  timeoutMs: number;
  logPayloads?: boolean;
  logger?: BridgeLogger;
};

/**
 * KG-only client for the Kogwistar bridge.
 *
 * Handles all Knowledge Graph CRUD operations.
 * Does NOT handle governance operations — those belong in plugin-governance.
 *
 * Logging: when logPayloads is true, request payloads are logged as-is via
 * the plugin logger. KG payloads are tool-call inputs from OpenClaw — they
 * are not governance-sensitive, so full logging is acceptable here. If a
 * field-level redaction policy is ever needed, add a KG-specific debug
 * projection using titanic-expedition.
 */
export class KogwistarBridgeClient {
  private readonly transport: BridgeTransport;
  private readonly logPayloads: boolean;
  private readonly logger: BridgeLogger | undefined;

  constructor(opts: KgClientOptions) {
    this.transport = new BridgeTransport({
      bridgeUrl: opts.bridgeUrl,
      timeoutMs: opts.timeoutMs,
      logger: opts.logger,
    });
    this.logPayloads = Boolean(opts.logPayloads);
    this.logger = opts.logger;
  }

  private log(path: string, payload: unknown): void {
    if (this.logPayloads) {
      this.logger?.debug?.(
        `[kogwistar-kg] POST ${path} ${JSON.stringify(payload)}`
      );
    }
  }

  private async post<T>(path: string, payload: unknown): Promise<T> {
    this.log(path, payload);
    return this.transport.post<T>(path, payload);
  }

  // ---------------------------------------------------------------------------
  // Node operations
  // ---------------------------------------------------------------------------

  async kgNodeCreate(payload: Record<string, unknown>): Promise<{ ok: boolean; id: string }> {
    return this.post<{ ok: boolean; id: string }>("/kg/node/create", payload);
  }

  async kgNodeGet(payload: Record<string, unknown>): Promise<{ ok: boolean; nodes: unknown[] }> {
    return this.post<{ ok: boolean; nodes: unknown[] }>("/kg/node/get", payload);
  }

  async kgNodeDelete(nodeId: string): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>("/kg/node/delete", { node_id: nodeId });
  }

  async kgNodeUpdate(payload: Record<string, unknown>): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>("/kg/node/update", payload);
  }

  // ---------------------------------------------------------------------------
  // Edge operations
  // ---------------------------------------------------------------------------

  async kgEdgeCreate(payload: Record<string, unknown>): Promise<{ ok: boolean; id: string }> {
    return this.post<{ ok: boolean; id: string }>("/kg/edge/create", payload);
  }

  async kgEdgeGet(payload: Record<string, unknown>): Promise<{ ok: boolean; edges: unknown[] }> {
    return this.post<{ ok: boolean; edges: unknown[] }>("/kg/edge/get", payload);
  }

  async kgEdgeDelete(edgeId: string): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>("/kg/edge/delete", { edge_id: edgeId });
  }

  async kgEdgeUpdate(payload: Record<string, unknown>): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>("/kg/edge/update", payload);
  }

  // ---------------------------------------------------------------------------
  // Query
  // ---------------------------------------------------------------------------

  async kgQuery(payload: Record<string, unknown>): Promise<{ ok: boolean; nodes: unknown[] }> {
    return this.post<{ ok: boolean; nodes: unknown[] }>("/kg/query", payload);
  }
}
