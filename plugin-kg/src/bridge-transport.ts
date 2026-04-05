/** Minimal logger interface — no openclaw SDK dependency in the transport layer. */
export type BridgeLogger = {
  debug?: (msg: string) => void;
};

export type TransportOptions = {
  bridgeUrl: string;
  timeoutMs: number;
  logger?: BridgeLogger;
};

/**
 * Domain-agnostic HTTP transport for the Kogwistar bridge.
 *
 * Shared structural pattern with plugin-governance/src/bridge-transport.ts.
 * These two packages are separate NPM packages and do not share code at
 * runtime, so the transport is deliberately duplicated rather than extracted
 * to a shared dep. If a shared `@kogwistar/bridge-transport` package is
 * introduced later, both copies should be replaced.
 *
 * This class knows nothing about governance or KG semantics.
 * Callers are responsible for passing correctly projected payloads.
 */
export class BridgeTransport {
  readonly baseUrl: string;
  private readonly timeoutMs: number;
  protected readonly logger: BridgeLogger | undefined;

  constructor(opts: TransportOptions) {
    this.baseUrl = opts.bridgeUrl.replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs;
    this.logger = opts.logger;
  }

  async post<T>(path: string, wirePayload: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const fullUrl = `${this.baseUrl}${path}`;
      const res = await fetch(fullUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(wirePayload),
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
}
