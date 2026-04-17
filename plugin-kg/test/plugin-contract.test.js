import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import plugin from "../dist/index.js";

test("KG plugin entry exposes the expected public contract", () => {
  assert.equal(plugin.id, "kogwistar-kg");
  assert.equal(plugin.name, "Kogwistar Knowledge Graph");
  assert.equal(
    plugin.description,
    "Exposes Kogwistar Knowledge Graph CRUD operations as OpenClaw tools"
  );
  assert.equal(typeof plugin.register, "function");
  assert.ok(plugin.configSchema);
  assert.equal(plugin.configSchema.jsonSchema.type, "object");
  assert.equal(plugin.configSchema.jsonSchema.additionalProperties, false);
});

test("KG plugin package metadata points at the built extension surface", async () => {
  const manifestPath = fileURLToPath(new URL("../openclaw.plugin.json", import.meta.url));
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  assert.deepEqual(manifest, {
    id: "kogwistar-kg",
    name: "Kogwistar Knowledge Graph",
    description: "Exposes Kogwistar Knowledge Graph CRUD operations as OpenClaw tools",
    version: "0.1.0",
    type: "module",
    configSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        bridgeUrl: {
          type: "string",
          default: "http://127.0.0.1:8799",
        },
        requestTimeoutMs: {
          type: "number",
          default: 30000,
        },
        logPayloads: {
          type: "boolean",
          default: false,
        },
      },
    },
    openclaw: {
      extensions: ["./dist/index.js"],
      compat: {
        pluginApi: ">=2026.3.28",
        minGatewayVersion: "2026.3.28",
      },
      build: {
        openclawVersion: "2026.3.28",
        pluginSdkVersion: "2026.3.28",
      },
    },
  });
});
