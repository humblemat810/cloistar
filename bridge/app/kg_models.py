from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from pydantic import BaseModel, Field

class NodeCreateIn(BaseModel):
    label: str
    type: str = "entity"
    summary: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    doc_id: Optional[str] = None

class NodeGetIn(BaseModel):
    ids: Optional[List[str]] = None
    node_type: Optional[str] = None
    where: Optional[Dict[str, Any]] = None
    limit: Optional[int] = 200
    resolve_mode: Literal["active_only", "redirect", "include_tombstones"] = "active_only"

class NodeUpdateIn(BaseModel):
    from_id: str
    to_id: str

class NodeDeleteIn(BaseModel):
    node_id: str

class EdgeCreateIn(BaseModel):
    relation: str
    source_ids: List[str]
    target_ids: List[str]
    label: Optional[str] = None
    summary: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    doc_id: Optional[str] = None

class EdgeGetIn(BaseModel):
    ids: Optional[List[str]] = None
    edge_type: Optional[str] = None
    where: Optional[Dict[str, Any]] = None
    limit: Optional[int] = 400
    resolve_mode: Literal["active_only", "redirect", "include_tombstones"] = "active_only"

class EdgeUpdateIn(BaseModel):
    from_id: str
    to_id: str

class EdgeDeleteIn(BaseModel):
    edge_id: str

class QueryIn(BaseModel):
    query: Optional[str] = None
    query_embeddings: Optional[List[List[float]]] = None
    where: Optional[Dict[str, Any]] = None
    n_results: int = 20
    node_type: Optional[str] = None
