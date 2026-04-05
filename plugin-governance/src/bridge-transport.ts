/** Minimal logger interface. Avoids a hard dependency on the openclaw SDK in the transport layer. */
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
 * This class knows nothing about governance or KG semantics.
 * It sends exactly what it receives and returns exactly what the bridge sends.
 *
 * Callers are responsible for:
 *   - passing a correctly projected WIRE payload (not internal or raw)
 *   - logging the DEBUG projection before calling post()
 *   - never passing the same object to both log and post
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
