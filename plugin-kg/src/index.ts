import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { KogwistarBridgeClient } from "./kogwistar-client.js";
import { Type } from "@sinclair/typebox";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/plugin-entry";
import { sanitizeKgResultForLlm } from "./llm-safe.js";

type PluginConfig = {
  bridgeUrl: string;
  requestTimeoutMs: number;
  logPayloads?: boolean;
};

function llmToolResult(result: Record<string, unknown>) {
  const safeResult = sanitizeKgResultForLlm(result);
  const content = [{ type: "text" as const, text: JSON.stringify(safeResult) }];
  return {
    content,
    details: safeResult,
  };
}

export default definePluginEntry({
  id: "kogwistar-kg",
  name: "Kogwistar Knowledge Graph",
  description: "Exposes Kogwistar Knowledge Graph CRUD operations as OpenClaw tools",
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
          default: 30000,
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
      timeoutMs: cfg.requestTimeoutMs ?? 30000,
      logPayloads: cfg.logPayloads ?? false,
      logger: api.logger,
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
        return llmToolResult(result);
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
        return llmToolResult(result);
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
        return llmToolResult(result);
      },
    });

    api.registerTool({
      name: "kg_update_node",
      label: "KG: Update Node (Redirect)",
      description: "Redirect an old node ID to a new node ID",
      parameters: Type.Object({
        from_id: Type.String(),
        to_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgNodeUpdate(params);
        return llmToolResult(result);
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
        return llmToolResult(result);
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
        return llmToolResult(result);
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
        return llmToolResult(result);
      },
    });

    api.registerTool({
      name: "kg_update_edge",
      label: "KG: Update Edge (Redirect)",
      description: "Redirect an old edge ID to a new edge ID",
      parameters: Type.Object({
        from_id: Type.String(),
        to_id: Type.String(),
      }),
      async execute(_id, params) {
        const result = await client.kgEdgeUpdate(params);
        return llmToolResult(result);
      },
    });

    api.registerTool({
      name: "kg_query",
      label: "KG: Query Nodes",
      description: "Search for nodes in the knowledge graph using semantic query",
      parameters: Type.Object({
        query: Type.String(),
        where: Type.Optional(Type.Record(Type.String(), Type.Any())),
        limit: Type.Number({ default: 20 }),
      }),
      async execute(_id, params) {
        const result = await client.kgQuery(params);
        return llmToolResult(result);
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
          const payload = {
            label: opts.label,
            type: opts.type,
            summary: opts.summary,
            properties: opts.properties,
            metadata: opts.metadata,
            doc_id: opts.docId,
          };
          const result = await client.kgNodeCreate(payload);
          process.stdout.write(JSON.stringify(result, null, 2) + "\n");
        });

      node
        .command("get")
        .description("Retrieve nodes")
        .option("--ids <ids...>", "Node IDs")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 200)
        .option("--resolve-mode <mode>", "Active only, redirect, or include tombstones", "active_only")
        .action(async (opts) => {
          const payload = {
            ...opts,
            resolve_mode: opts.resolveMode,
          };
          const result = await client.kgNodeGet(payload);
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
          process.stdout.write(JSON.stringify(result, null, 2) + "\n");
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
          const payload = {
            relation: opts.relation,
            source_ids: opts.sourceIds,
            target_ids: opts.targetIds,
            label: opts.label,
            summary: opts.summary,
            properties: opts.properties,
            metadata: opts.metadata,
            doc_id: opts.docId,
          };
          const result = await client.kgEdgeCreate(payload);
          process.stdout.write(JSON.stringify(result, null, 2) + "\n");
        });

      edge
        .command("get")
        .description("Retrieve edges")
        .option("--ids <ids...>", "Edge IDs")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 400)
        .option("--resolve-mode <mode>", "Active only, redirect, or include tombstones", "active_only")
        .action(async (opts) => {
          const payload = {
            ...opts,
            resolve_mode: opts.resolveMode,
          };
          const result = await client.kgEdgeGet(payload);
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
          process.stdout.write(JSON.stringify(result, null, 2) + "\n");
        });

      kg.command("query <query>")
        .description("Semantic search for nodes")
        .option("--where <json>", "Where filter (JSON)", (val) => JSON.parse(val))
        .option("--limit <limit>", "Limit result count", (val) => parseInt(val, 10), 20)
        .action(async (query, opts) => {
          const result = await client.kgQuery({ query, ...opts });
          process.stdout.write(JSON.stringify(result, null, 2) + "\n");
        });
    }, {
      descriptors: [{ name: "kg", description: "Kogwistar Knowledge Graph CRUD", hasSubcommands: true }]
    });
  },
});
