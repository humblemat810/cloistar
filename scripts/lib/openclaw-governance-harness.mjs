import { spawn } from "node:child_process";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * Shared live-test harness for the OpenClaw governance bridge.
 *
 * Use this module when you need to:
 * - start the real FastAPI bridge against the repo's Python venv
 * - load the built plugin entrypoint and capture registered hook handlers
 * - inspect bridge state after a live policy / approval round-trip
 *
 * It is intentionally reusable by both the automated live test and the manual
 * smoke script so the two paths exercise the same setup logic.
 */
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const repoRoot = path.resolve(__dirname, "..", "..");
export const bridgePython = path.join(repoRoot, ".venv", "bin", "python");
const pluginEntryUrl = pathToFileURL(path.join(repoRoot, "plugin", "dist", "index.js")).href;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Find an unused loopback port for a temporary bridge instance.
 */
export async function pickFreePort() {
  return await new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        server.close();
        reject(new Error("failed to allocate a loopback port"));
        return;
      }
      const { port } = address;
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve(port);
      });
    });
    server.on("error", reject);
  });
}

/**
 * Poll the bridge health endpoint until it becomes reachable.
 */
export async function waitForBridge(bridgeUrl, timeoutMs = 10_000) {
  const startedAt = Date.now();
  let lastError = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(`${bridgeUrl}/healthz`);
      if (response.ok) {
        return;
      }
      lastError = new Error(`healthz returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }

  throw new Error(
    `bridge failed to become healthy at ${bridgeUrl}: ${lastError ? String(lastError) : "timeout"}`
  );
}

/**
 * Spawn the repo-local bridge process and wait until it serves /healthz.
 *
 * This is the safest way to validate the live integration in-process because
 * it guarantees we are talking to the bridge from this checkout, not some
 * already-running container or unrelated service.
 */
export async function startBridge({
  port,
  host = "127.0.0.1",
  streamOutput = false,
  extraEnv = {},
} = {}) {
  const resolvedPort = port ?? (await pickFreePort());
  const bridgeUrl = `http://${host}:${resolvedPort}`;
  const stdout = [];
  const stderr = [];
  const env = {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH
      ? `${repoRoot}${path.delimiter}${process.env.PYTHONPATH}`
      : repoRoot,
    ...extraEnv,
  };

  const child = spawn(
    bridgePython,
    ["-m", "uvicorn", "bridge.app.main:app", "--host", host, "--port", String(resolvedPort)],
    {
      cwd: repoRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout.push(chunk);
    if (streamOutput) {
      process.stdout.write(`[bridge] ${chunk}`);
    }
  });
  child.stderr.on("data", (chunk) => {
    stderr.push(chunk);
    if (streamOutput) {
      process.stderr.write(`[bridge] ${chunk}`);
    }
  });

  try {
    const startedAt = Date.now();
    let lastError = null;
    while (Date.now() - startedAt < 10_000) {
      if (child.exitCode !== null) {
        throw new Error(
          `bridge process exited before becoming healthy (code=${child.exitCode})`
        );
      }
      try {
        const response = await fetch(`${bridgeUrl}/healthz`);
        if (response.ok) {
          break;
        }
        lastError = new Error(`healthz returned ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      await sleep(100);
    }
    if (child.exitCode !== null) {
      throw new Error(`bridge process exited before becoming healthy (code=${child.exitCode})`);
    }
    if (Date.now() - startedAt >= 10_000) {
      throw new Error(lastError ? String(lastError) : "timed out waiting for healthz");
    }
  } catch (error) {
    child.kill("SIGTERM");
    throw new Error(
      `failed to start bridge process: ${String(error)}\n${stderr.join("") || stdout.join("")}`
    );
  }

  return {
    bridgeUrl,
    host,
    port: resolvedPort,
    child,
    stdout,
    stderr,
    async stop() {
      if (child.exitCode !== null) {
        return;
      }
      child.kill("SIGTERM");
      await new Promise((resolve) => {
        child.once("exit", resolve);
      });
    },
  };
}

/**
 * Load the built plugin entry and capture the hook handlers it registers.
 *
 * The returned beforeToolCall / afterToolCall functions are the exact handler
 * functions OpenClaw would call through the plugin runtime.
 */
export async function loadPluginHandlers({
  bridgeUrl,
  requestTimeoutMs = 3_000,
  defaultSeverity = "warning",
  logPayloads = true,
} = {}) {
  const { default: plugin } = await import(pluginEntryUrl);
  const handlers = new Map();
  const logs = [];

  plugin.register({
    id: plugin.id,
    pluginConfig: {
      bridgeUrl,
      requestTimeoutMs,
      defaultSeverity,
      logPayloads,
    },
    logger: {
      debug(message) {
        logs.push({ level: "debug", message });
      },
      info(message) {
        logs.push({ level: "info", message });
      },
      warn(message) {
        logs.push({ level: "warn", message });
      },
      error(message) {
        logs.push({ level: "error", message });
      },
    },
    on(name, handler, options) {
      handlers.set(name, { handler, options });
    },
  });

  return {
    plugin,
    logs,
    handlers,
    beforeToolCall: handlers.get("before_tool_call")?.handler,
    afterToolCall: handlers.get("after_tool_call")?.handler,
  };
}

/**
 * Read the bridge's debug state snapshot for assertions or human-readable logs.
 */
export async function fetchBridgeState(bridgeUrl) {
  const response = await fetch(`${bridgeUrl}/debug/state`);
  if (!response.ok) {
    throw new Error(`debug/state returned ${response.status}`);
  }
  return await response.json();
}

/**
 * Make hook results printable in smoke output by replacing function values.
 */
export function serializeHookResult(value) {
  return JSON.parse(
    JSON.stringify(value, (_key, current) => {
      if (typeof current === "function") {
        return "[Function]";
      }
      return current;
    })
  );
}
