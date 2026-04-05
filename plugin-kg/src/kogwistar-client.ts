import type { PluginLogger } from "openclaw/plugin-sdk/plugin-entry";

type ClientOptions = {
  bridgeUrl: string;
  timeoutMs: number;
  logPayloads?: boolean;
  logger?: PluginLogger;
};

export class KogwistarBridgeClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly logPayloads: boolean;
  private readonly logger: ClientOptions["logger"];

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.bridgeUrl.replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs;
    this.logPayloads = Boolean(opts.logPayloads);
    this.logger = opts.logger;
  }

  private async postJson<T>(path: string, payload: unknown): Promise<T> {
    if (this.logPayloads) {
      this.logger?.debug?.(`[kogwistar] POST ${path} ${JSON.stringify(payload)}`);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const fullUrl = `${this.baseUrl}${path}`;
      const res = await fetch(fullUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`Bridge error ${res.status}: ${body}`);
      }

      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  async kgNodeCreate(payload: Record<string, unknown>): Promise<{ ok: boolean; id: string }> {
    return this.postJson<{ ok: boolean; id: string }>("/kg/node/create", payload);
  }

  async kgNodeGet(payload: Record<string, unknown>): Promise<{ ok: boolean; nodes: any[] }> {
    return this.postJson<{ ok: boolean; nodes: any[] }>("/kg/node/get", payload);
  }

  async kgNodeDelete(nodeId: string): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>("/kg/node/delete", { node_id: nodeId });
  }

  async kgNodeUpdate(payload: Record<string, unknown>): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>("/kg/node/update", payload);
  }

  async kgEdgeCreate(payload: Record<string, unknown>): Promise<{ ok: boolean; id: string }> {
    return this.postJson<{ ok: boolean; id: string }>("/kg/edge/create", payload);
  }

  async kgEdgeGet(payload: Record<string, unknown>): Promise<{ ok: boolean; edges: any[] }> {
    return this.postJson<{ ok: boolean; edges: any[] }>("/kg/edge/get", payload);
  }

  async kgEdgeDelete(edgeId: string): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>("/kg/edge/delete", { edge_id: edgeId });
  }

  async kgEdgeUpdate(payload: Record<string, unknown>): Promise<{ ok: boolean }> {
    return this.postJson<{ ok: boolean }>("/kg/edge/update", payload);
  }

  async kgQuery(payload: Record<string, unknown>): Promise<{ ok: boolean; nodes: any[] }> {
    return this.postJson<{ ok: boolean; nodes: any[] }>("/kg/query", payload);
  }
}
