from __future__ import annotations

from kogwistar.engine_core.models import Grounding, Span
from kogwistar.runtime.models import WorkflowDesignArtifact, WorkflowEdge, WorkflowNode


GOVERNANCE_WORKFLOW_ID = "kogwistar.governance.openclaw.v1"


def _span(workflow_id: str) -> Span:
    return Span.from_dummy_for_workflow(workflow_id)


def _node(
    *,
    workflow_id: str,
    node_id: str,
    label: str,
    op: str,
    start: bool = False,
    terminal: bool = False,
) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        label=label,
        type="entity",
        doc_id=node_id,
        summary=op,
        mentions=[Grounding(spans=[_span(workflow_id)])],
        properties={},
        metadata={
            "entity_type": "workflow_node",
            "workflow_id": workflow_id,
            "wf_op": op,
            "wf_start": start,
            "wf_terminal": terminal,
            "wf_version": "v1",
        },
        domain_id=None,
        canonical_entity_id=None,
    )


def _edge(
    *,
    workflow_id: str,
    edge_id: str,
    src: str,
    dst: str,
) -> WorkflowEdge:
    return WorkflowEdge(
        id=edge_id,
        source_ids=[src],
        target_ids=[dst],
        relation="wf_next",
        label="wf_next",
        type="relationship",
        summary="next",
        doc_id=workflow_id,
        mentions=[Grounding(spans=[_span(workflow_id)])],
        properties={},
        metadata={
            "entity_type": "workflow_edge",
            "workflow_id": workflow_id,
            "wf_priority": 100,
            "wf_is_default": True,
            "wf_predicate": None,
            "wf_multiplicity": "one",
        },
        source_edge_ids=[],
        target_edge_ids=[],
        domain_id=None,
        canonical_entity_id=None,
    )


def build_governance_workflow_design(
    *,
    workflow_id: str = GOVERNANCE_WORKFLOW_ID,
) -> WorkflowDesignArtifact:
    wid = lambda suffix: f"wf|{workflow_id}|{suffix}"

    # The approval branch is intentionally modeled as a suspend/resume loop:
    # the workflow pauses at "approval" and waits for an external resolution
    # event to re-enter the run and continue toward grant or deny.
    nodes = [
        _node(
            workflow_id=workflow_id,
            node_id=wid("ingest"),
            label="Ingest Proposal",
            op="ingest_proposal",
            start=True,
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("load-context"),
            label="Load Prior Context",
            op="load_prior_context",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("classify-risk"),
            label="Classify Risk",
            op="classify_risk",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("decide"),
            label="Decide Governance",
            op="decide_governance",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("allow"),
            label="Record Allow",
            op="record_allow",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("block"),
            label="Record Block",
            op="record_block",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("approval"),
            label="Request Approval",
            op="request_approval",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("approval-granted"),
            label="Record Approval Granted",
            op="record_approval_granted",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("approval-denied"),
            label="Record Approval Denied",
            op="record_approval_denied",
        ),
        _node(
            workflow_id=workflow_id,
            node_id=wid("close"),
            label="Close Run",
            op="close_run",
            terminal=True,
        ),
    ]

    edges = [
        _edge(workflow_id=workflow_id, edge_id=wid("e|ingest->load-context"), src=wid("ingest"), dst=wid("load-context")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|load-context->classify-risk"), src=wid("load-context"), dst=wid("classify-risk")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|classify-risk->decide"), src=wid("classify-risk"), dst=wid("decide")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|decide->allow"), src=wid("decide"), dst=wid("allow")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|decide->block"), src=wid("decide"), dst=wid("block")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|decide->approval"), src=wid("decide"), dst=wid("approval")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|allow->close"), src=wid("allow"), dst=wid("close")),
        _edge(workflow_id=workflow_id, edge_id=wid("e|block->close"), src=wid("block"), dst=wid("close")),
        _edge(
            workflow_id=workflow_id,
            edge_id=wid("e|approval->approval-granted"),
            src=wid("approval"),
            dst=wid("approval-granted"),
        ),
        _edge(
            workflow_id=workflow_id,
            edge_id=wid("e|approval->approval-denied"),
            src=wid("approval"),
            dst=wid("approval-denied"),
        ),
        _edge(
            workflow_id=workflow_id,
            edge_id=wid("e|approval-granted->close"),
            src=wid("approval-granted"),
            dst=wid("close"),
        ),
        _edge(
            workflow_id=workflow_id,
            edge_id=wid("e|approval-denied->close"),
            src=wid("approval-denied"),
            dst=wid("close"),
        ),
    ]

    return WorkflowDesignArtifact(
        workflow_id=workflow_id,
        workflow_version="v1",
        start_node_id=wid("ingest"),
        nodes=nodes,
        edges=edges,
    )


def ensure_governance_workflow_design(workflow_engine, *, workflow_id: str = GOVERNANCE_WORKFLOW_ID) -> None:
    existing = workflow_engine.get_nodes(
        where={"$and": [{"entity_type": "workflow_node"}, {"workflow_id": workflow_id}]},
        limit=1000,
    )
    if existing:
        return

    design = build_governance_workflow_design(workflow_id=workflow_id)
    for node in design.nodes:
        workflow_engine.write.add_node(node)
    for edge in design.edges:
        workflow_engine.write.add_edge(edge)
