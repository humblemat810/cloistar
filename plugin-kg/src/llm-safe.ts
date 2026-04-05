function maybeString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function maybeStringArray(value: unknown): string[] | undefined {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : undefined;
}

function compactRecord(record: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined));
}

function sanitizeNode(node: Record<string, unknown>): Record<string, unknown> {
  const metadata =
    node.metadata && typeof node.metadata === "object"
      ? (node.metadata as Record<string, unknown>)
      : {};
  return compactRecord({
    id: maybeString(node.id),
    label: maybeString(node.label),
    type: maybeString(node.type),
    summary: maybeString(node.summary),
    doc_id: maybeString(node.doc_id),
    entity_type: maybeString(metadata.entity_type),
    relation_kind: maybeString(metadata.relation_kind),
  });
}

function sanitizeEdge(edge: Record<string, unknown>): Record<string, unknown> {
  const metadata =
    edge.metadata && typeof edge.metadata === "object"
      ? (edge.metadata as Record<string, unknown>)
      : {};
  return compactRecord({
    id: maybeString(edge.id),
    label: maybeString(edge.label),
    type: maybeString(edge.type),
    relation: maybeString(edge.relation),
    summary: maybeString(edge.summary),
    source_ids: maybeStringArray(edge.source_ids),
    target_ids: maybeStringArray(edge.target_ids),
    doc_id: maybeString(edge.doc_id),
    relation_kind: maybeString(metadata.relation_kind),
    entity_type: maybeString(metadata.entity_type),
  });
}

function copyScalarTopLevel(result: Record<string, unknown>): Record<string, unknown> {
  return compactRecord({
    ok: result.ok,
    id: maybeString(result.id),
    error: maybeString(result.error),
    message: maybeString(result.message),
    status: maybeString(result.status),
  });
}

export function sanitizeKgResultForLlm(result: Record<string, unknown>): Record<string, unknown> {
  const safe: Record<string, unknown> = copyScalarTopLevel(result);
  if (Array.isArray(result.nodes)) {
    safe.nodes = result.nodes.map((node) =>
      node && typeof node === "object" ? sanitizeNode(node as Record<string, unknown>) : node
    );
  }
  if (Array.isArray(result.edges)) {
    safe.edges = result.edges.map((edge) =>
      edge && typeof edge === "object" ? sanitizeEdge(edge as Record<string, unknown>) : edge
    );
  }
  return safe;
}
