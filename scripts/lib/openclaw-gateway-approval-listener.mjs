import fs from "node:fs/promises";
import process from "node:process";
// Use OpenClaw only through its compiled package surface. We do not patch or
// depend on openclaw/src for the live approval workflow.
import { createOperatorApprovalsGatewayClient } from "../../openclaw/dist/plugin-sdk/gateway-runtime.js";

const bridgeUrl = (process.env.BRIDGE_URL || "").replace(/\/+$/, "");
const configPath = process.env.OPENCLAW_CONFIG_PATH || "";

if (!bridgeUrl) {
  throw new Error("BRIDGE_URL is required");
}

if (!configPath) {
  throw new Error("OPENCLAW_CONFIG_PATH is required");
}

async function loadConfig() {
  const raw = await fs.readFile(configPath, "utf8");
  return JSON.parse(raw);
}

async function postJson(path, payload) {
  const response = await fetch(`${bridgeUrl}${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
}

async function postStatus(payload) {
  await postJson("/gateway/approval-subscription/status", {
    ...payload,
    lastStatusAt: Date.now(),
  });
}

const cfg = await loadConfig();
await postStatus({
  enabled: true,
  started: true,
  connected: false,
  lastError: null,
});
const client = await createOperatorApprovalsGatewayClient({
  config: cfg,
  clientDisplayName: "Kogwistar bridge approvals",
  onHelloOk: () => {
    void postStatus({
      enabled: true,
      started: true,
      connected: true,
      lastError: null,
    }).catch(() => undefined);
    process.stderr.write("bridge approvals listener: connected to gateway\n");
  },
  onConnectError: (error) => {
    void postStatus({
      enabled: true,
      started: true,
      connected: false,
      lastError: String(error),
    }).catch(() => undefined);
    process.stderr.write(`bridge approvals listener: connect error: ${String(error)}\n`);
  },
  onClose: (code, reason) => {
    void postStatus({
      enabled: true,
      started: true,
      connected: false,
      lastError: `gateway closed (${code}): ${reason || "no close reason"}`,
    }).catch(() => undefined);
    process.stderr.write(
      `bridge approvals listener: gateway closed (${code}): ${reason || "no close reason"}\n`,
    );
  },
  onEvent: (event) => {
    if (event.event === "plugin.approval.requested") {
      void postStatus({
        enabled: true,
        started: true,
        connected: true,
        lastError: null,
        lastRequestedEventAt: event.payload?.createdAtMs ?? Date.now(),
      }).catch(() => undefined);
      void postJson("/gateway/plugin-approval/requested", event.payload ?? {}).catch((error) => {
        process.stderr.write(
          `bridge approvals listener: failed to post requested event: ${String(error)}\n`,
        );
      });
      return;
    }
    if (event.event === "plugin.approval.resolved") {
      void postStatus({
        enabled: true,
        started: true,
        connected: true,
        lastError: null,
        lastResolvedEventAt: event.payload?.ts ?? Date.now(),
      }).catch(() => undefined);
      void postJson("/gateway/plugin-approval/resolved", event.payload ?? {}).catch((error) => {
        process.stderr.write(
          `bridge approvals listener: failed to post resolved event: ${String(error)}\n`,
        );
      });
    }
  },
});

const stop = async () => {
  await client.stopAndWait().catch(() => undefined);
  process.exit(0);
};

process.on("SIGINT", () => {
  void stop();
});
process.on("SIGTERM", () => {
  void stop();
});

client.start();
await new Promise(() => {});
