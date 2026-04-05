import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { KogwistarBridgeClient } from "./kogwistar-client.js";
import { Type } from "@sinclair/typebox";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import {
  type GovernanceApprovalResolution,
  buildAfterToolCallPayload,
  buildApprovalResolutionPayload,
  buildBeforeToolCallPayload,
  decisionToHookResult,
} from "./governance-contract.js";

type PluginConfig = {
  bridgeUrl: string;
  requestTimeoutMs?: number;
  defaultSeverity?: "info" | "warning" | "critical";
  logPayloads?: boolean;
};

export default definePluginEntry({
  id: "kogwistar-governance",
  name: "Kogwistar Governance",
  description: "Delegates OpenClaw tool governance decisions to a Kogwistar bridge",
  configSchema: {
    jsonSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        bridgeUrl: {
          type: "string",
          default: "http://127.0.0.1:8799",
        },
        requestTimeoutMs: {
          type: "number",
          default: 3000,
        },
        defaultSeverity: {
          anyOf: [
            { type: "string", const: "info" },
            { type: "string", const: "warning" },
            { type: "string", const: "critical" },
          ],
        },
        logPayloads: {
          type: "boolean",
          default: false,
        },
      },
    },
  },
  register(api: OpenClawPluginApi) {
    const cfg = (api.pluginConfig ?? {}) as PluginConfig;
    const client = new KogwistarBridgeClient({
      bridgeUrl: cfg.bridgeUrl ?? "http://127.0.0.1:8799",
      timeoutMs: cfg.requestTimeoutMs ?? 3000,
      logPayloads: cfg.logPayloads,
      logger: api.logger,
    });

    api.on(
      "before_tool_call",
      async (event, ctx) => {
        const payload = buildBeforeToolCallPayload(api.id, event, ctx);
        const decision = await client.evaluateBeforeToolCall(payload);

        return decisionToHookResult({
          decision,
          defaultSeverity: cfg.defaultSeverity,
          onResolution: async (resolution: GovernanceApprovalResolution) => {
            await client.emitApprovalResolution(
              buildApprovalResolutionPayload({
                pluginId: api.id,
                event,
                ctx,
                resolution,
                approvalId: decision.decision === "requireApproval" ? decision.approvalId ?? null : null,
              })
            );
          },
        });
      },
      { priority: 100 }
    );

    api.on("after_tool_call", async (event, ctx) => {
      await client.emitAfterToolCall(buildAfterToolCallPayload(api.id, event, ctx));
    });

    // --- KG CRUD Tools ---

    api.registerTool({
      name: "kg_create_node",
      label: "KG: Create Node",
      description: "Create a new node in the knowledge graph",
      parameters: Type.Object({
        label: Type.String(),
        type: Type.String({ default: "entity" }),
        summary: Type.Optional(Type.String()),
        properties: Type.Optional(Type.Record(Type.String(), Type.Any())),
        metadata: Type.Optional(Type.Record(Type.String(), Type.Any())),
        doc_id: Type.Optional(Type.String()),
      }),
      async execute(_id, params) {
        const result = await client.kgNodeCreate(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_get_nodes",
      label: "KG: Get Nodes",
      description: "Retrieve nodes from the knowledge graph",
      parameters: Type.Object({
        ids: Type.Optional(Type.Array(Type.String())),
        where: Type.Optional(Type.Record(Type.String(), Type.Any())),
        limit: Type.Number({ default: 200 }),
        resolve_mode: Type.String({
          enum: ["active_only", "redirect", "include_tombstones"],
          default: "active_only",
        }),
      }),
      async execute(_id, params) {
        const result = await client.kgNodeGet(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_delete_node",
      label: "KG: Delete Node",
      description: "Tombstone a node in the knowledge graph",
      parameters: Type.Object({
        node_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgNodeDelete(params.node_id);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_update_node",
      label: "KG: Update Node",
      description: "Redirect an old node to a new node (update semantics)",
      parameters: Type.Object({
        from_id: Type.String(),
        to_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgNodeUpdate(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_create_edge",
      label: "KG: Create Edge",
      description: "Create a new edge in the knowledge graph",
      parameters: Type.Object({
        relation: Type.String(),
        source_ids: Type.Array(Type.String()),
        target_ids: Type.Array(Type.String()),
        label: Type.Optional(Type.String()),
        summary: Type.Optional(Type.String()),
        properties: Type.Optional(Type.Record(Type.String(), Type.Any())),
        metadata: Type.Optional(Type.Record(Type.String(), Type.Any())),
        doc_id: Type.Optional(Type.String()),
      }),
      async execute(_id, params) {
        const result = await client.kgEdgeCreate(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_get_edges",
      label: "KG: Get Edges",
      description: "Retrieve edges from the knowledge graph",
      parameters: Type.Object({
        ids: Type.Optional(Type.Array(Type.String())),
        where: Type.Optional(Type.Record(Type.String(), Type.Any())),
        limit: Type.Number({ default: 400 }),
        resolve_mode: Type.String({
          enum: ["active_only", "redirect", "include_tombstones"],
          default: "active_only",
        }),
      }),
      async execute(_id, params) {
        const result = await client.kgEdgeGet(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_delete_edge",
      label: "KG: Delete Edge",
      description: "Tombstone an edge in the knowledge graph",
      parameters: Type.Object({
        edge_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgEdgeDelete(params.edge_id);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_update_edge",
      label: "KG: Update Edge",
      description: "Redirect an old edge to a new edge (update semantics)",
      parameters: Type.Object({
        from_id: Type.String(),
        to_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgEdgeUpdate(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "kg_query",
      label: "KG: Query",
      description: "Semantic search for nodes in the knowledge graph",
      parameters: Type.Object({
        query: Type.Optional(Type.String()),
        where: Type.Optional(Type.Record(Type.String(), Type.Any())),
        n_results: Type.Number({ default: 20 }),
      }),
      async execute(_id, params) {
        const result = await client.kgQuery(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    // --- KG CLI Commands ---

    api.registerCli((ctx) => {
      const kg = ctx.program.command("kg").description("Kogwistar Knowledge Graph CRUD");

      const node = kg.command("node").description("Node operations");
      node
        .command("create")
        .description("Create a new node")
        .requiredOption("--label <label>", "Node label")
        .option("--type <type>", "Node type", "entity")
        .option("--summary <summary>", "Node summary")
        .option("--properties <json>", "Node properties (JSON)", (val) => JSON.parse(val))
        .option("--metadata <json>", "Node metadata (JSON)", (val) => JSON.parse(val))
        .option("--doc-id <doc_id>", "Document ID")
        .action(async (opts) => {
          const result = await client.kgNodeCreate(opts);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      node
        .command("get")
        .description("Retrieve nodes")
        .option("--ids <ids...>", "Node IDs")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 200)
        .option("--resolve-mode <mode>", "Active only, redirect, or include tombstones", "active_only")
        .action(async (opts) => {
          const result = await client.kgNodeGet(opts);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      node
        .command("delete <node_id>")
        .description("Tombstone a node")
        .action(async (node_id) => {
          const result = await client.kgNodeDelete(node_id);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      node
        .command("update <from_id> <to_id>")
        .description("Redirect from one node to another")
        .action(async (from_id, to_id) => {
          const result = await client.kgNodeUpdate({ from_id, to_id });
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      const edge = kg.command("edge").description("Edge operations");
      edge
        .command("create")
        .description("Create a new edge")
        .requiredOption("--relation <relation>", "Edge relation type")
        .requiredOption("--source-ids <ids...>", "Source edge/node IDs")
        .requiredOption("--target-ids <ids...>", "Target edge/node IDs")
        .option("--label <label>", "Edge label")
        .option("--summary <summary>", "Edge summary")
        .option("--properties <json>", "Edge properties (JSON)", (val) => JSON.parse(val))
        .option("--metadata <json>", "Edge metadata (JSON)", (val) => JSON.parse(val))
        .option("--doc-id <doc_id>", "Document ID")
        .action(async (opts) => {
          const result = await client.kgEdgeCreate(opts);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      edge
        .command("get")
        .description("Retrieve edges")
        .option("--ids <ids...>", "Edge IDs")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 400)
        .option("--resolve-mode <mode>", "Active only, redirect, or include tombstones", "active_only")
        .action(async (opts) => {
          const result = await client.kgEdgeGet(opts);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      edge
        .command("delete <edge_id>")
        .description("Tombstone an edge")
        .action(async (edge_id) => {
          const result = await client.kgEdgeDelete(edge_id);
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      edge
        .command("update <from_id> <to_id>")
        .description("Redirect from one edge to another")
        .action(async (from_id, to_id) => {
          const result = await client.kgEdgeUpdate({ from_id, to_id });
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });

      kg.command("query <query>")
        .description("Semantic search for nodes")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 20)
        .action(async (query, opts) => {
          const result = await client.kgQuery({ query, ...opts });
          process.stderr.write(JSON.stringify(result, null, 2) + "\n");
        });
    }, {
      descriptors: [{ name: "kg", description: "Kogwistar Knowledge Graph CRUD", hasSubcommands: true }]
    });
  },
});
