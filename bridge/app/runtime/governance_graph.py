from __future__ import annotations

from typing import Any

from kogwistar.engine_core.models import Edge, Grounding, Node, Span


def governance_grounding(doc_id: str) -> list[Grounding]:
    return [Grounding(spans=[Span.from_dummy_for_conversation(doc_id)])]


def governance_node(
    *,
    node_id: str,
    label: str,
    summary: str,
    doc_id: str,
    metadata: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> Node:
    return Node(
        id=node_id,
        label=label,
        type="entity",
        doc_id=doc_id,
        summary=summary,
        mentions=governance_grounding(doc_id),
        properties=properties or {},
        metadata=metadata,
        domain_id=None,
        canonical_entity_id=None,
    )


def governance_edge(
    *,
    edge_id: str,
    source_id: str,
    target_id: str,
    relation: str,
    label: str,
    summary: str,
    doc_id: str,
    metadata: dict[str, Any] | None = None,
) -> Edge:
    return Edge(
        id=edge_id,
        source_ids=[source_id],
        target_ids=[target_id],
        relation=relation,
        label=label,
        type="relationship",
        summary=summary,
        doc_id=doc_id,
        mentions=governance_grounding(doc_id),
        properties={},
        metadata=metadata or {},
        source_edge_ids=[],
        target_edge_ids=[],
        domain_id=None,
        canonical_entity_id=None,
    )
