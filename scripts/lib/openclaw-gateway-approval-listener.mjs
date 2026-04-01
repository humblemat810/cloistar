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

const cfg = await loadConfig();
const client = await createOperatorApprovalsGatewayClient({
  config: cfg,
  clientDisplayName: "Kogwistar bridge approvals",
  onHelloOk: () => {
    process.stderr.write("bridge approvals listener: connected to gateway\n");
  },
  onConnectError: (error) => {
    process.stderr.write(`bridge approvals listener: connect error: ${String(error)}\n`);
  },
  onClose: (code, reason) => {
    process.stderr.write(
      `bridge approvals listener: gateway closed (${code}): ${reason || "no close reason"}\n`,
    );
  },
  onEvent: (event) => {
    if (event.event === "plugin.approval.requested") {
      void postJson("/gateway/plugin-approval/requested", event.payload ?? {}).catch((error) => {
        process.stderr.write(
          `bridge approvals listener: failed to post requested event: ${String(error)}\n`,
        );
      });
      return;
    }
    if (event.event === "plugin.approval.resolved") {
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
