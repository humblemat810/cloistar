import test from "node:test";
import assert from "node:assert/strict";

import { sanitizeKgResultForLlm } from "../dist/llm-safe.js";

test("sanitizeKgResultForLlm returns an explicit LLM-safe node shape instead of scrubbing backend blobs", () => {
  const result = sanitizeKgResultForLlm({
    ok: true,
    nodes: [
      {
        id: "n1",
        label: "Node 1",
        type: "entity",
        summary: "summary",
        doc_id: "doc-1",
        metadata: {
          entity_type: "governance_event",
          payload_json: "{\"secret\":true}",
          nested: { state_json: "{\"hidden\":1}", safe: "keep" },
        },
        properties: {
          safe: "keep",
          evaluation_json: "{\"tool\":\"exec\"}",
        },
        embedding: [1, 2, 3],
      },
    ],
  });

  assert.deepEqual(result, {
    ok: true,
    nodes: [
      {
        id: "n1",
        label: "Node 1",
        type: "entity",
        summary: "summary",
        doc_id: "doc-1",
        entity_type: "governance_event",
      },
    ],
  });
});

test("sanitizeKgResultForLlm returns an explicit LLM-safe edge shape instead of forwarding backend metadata", () => {
  const result = sanitizeKgResultForLlm({
    ok: true,
    id: "edge-created-1",
    edges: [
      {
        id: "e1",
        label: "edge",
        type: "relationship",
        relation: "related_to",
        summary: "edge summary",
        source_ids: ["n1"],
        target_ids: ["n2"],
        doc_id: "doc-e1",
        metadata: {
          resultJson: "{\"hidden\":2}",
          relation_kind: "semantic",
        },
        properties: {
          score: 1,
          payloadJson: "{\"hidden\":3}",
        },
      },
    ],
  });

  assert.deepEqual(result, {
    ok: true,
    id: "edge-created-1",
    edges: [
      {
        id: "e1",
        label: "edge",
        type: "relationship",
        relation: "related_to",
        summary: "edge summary",
        source_ids: ["n1"],
        target_ids: ["n2"],
        doc_id: "doc-e1",
        relation_kind: "semantic",
      },
    ],
  });
});
