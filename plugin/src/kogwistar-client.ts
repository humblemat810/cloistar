import type { PluginLogger } from "openclaw/plugin-sdk/plugin-entry";
import type {
  AfterToolCallPayload,
  BeforeToolCallPayload,
  GovernanceDecision,
} from "./governance-contract.js";

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
      const res = await fetch(`${this.baseUrl}${path}`, {
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

  async evaluateBeforeToolCall(payload: BeforeToolCallPayload): Promise<GovernanceDecision> {
    return this.postJson<GovernanceDecision>("/policy/before-tool-call", payload);
  }

  async emitAfterToolCall(payload: AfterToolCallPayload): Promise<{ ok: true }> {
    return this.postJson<{ ok: true }>("/events/after-tool-call", payload);
  }

  async emitApprovalResolution(payload: Record<string, unknown>): Promise<{ ok: true }> {
    return this.postJson<{ ok: true }>("/approval/resolution", payload);
  }
}
