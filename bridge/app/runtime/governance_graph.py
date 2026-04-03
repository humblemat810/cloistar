from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kogwistar.engine_core.models import Edge, Grounding, Node, Span
from kogwistar.engine_core.scoped_seq import ScopedSeqHookConfig, install_scoped_seq_hooks

if TYPE_CHECKING:
    from kogwistar.engine_core.engine import GraphKnowledgeEngine


GOVERNANCE_MAIN_BRANCH_ENTITY_TYPES = frozenset(
    {
        "governance_backbone_step",
        "governance_proposal",
        "governance_decision",
        "governance_approval_request",
        "governance_approval_resolution",
        "governance_completion",
    }
)


def governance_grounding(doc_id: str) -> list[Grounding]:
    return [Grounding(spans=[Span.from_dummy_for_conversation(doc_id)])]


def _governance_should_stamp_node(_engine: "GraphKnowledgeEngine", node: Any) -> bool:
    metadata = getattr(node, "metadata", {}) or {}
    return metadata.get("entity_type") in GOVERNANCE_MAIN_BRANCH_ENTITY_TYPES


def _governance_scope_id(_engine: "GraphKnowledgeEngine", node: Any) -> str | None:
    metadata = getattr(node, "metadata", {}) or {}
    governance_call_id = metadata.get("governance_call_id") or metadata.get("governanceCallId")
    if not governance_call_id:
        return None
    return f"governance:{governance_call_id}"


def install_governance_scoped_seq_hooks(engine: "GraphKnowledgeEngine") -> None:
    """Stamp governance main-branch nodes with a scoped append-only sequence.

    Governance uses a conversation-style append-only lineage, but it does not
    want to borrow the chat domain's conversation-id counter semantics. The
    scoped sequence hook gives governance its own monotonic `metadata["seq"]`
    stream per governance call id.
    """

    install_scoped_seq_hooks(
        engine,
        ScopedSeqHookConfig(
            metadata_field="seq",
            should_stamp_node=_governance_should_stamp_node,
            scope_id_for_node=_governance_scope_id,
        ),
        ready_attr="_governance_scoped_seq_hooks_ready",
    )


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
