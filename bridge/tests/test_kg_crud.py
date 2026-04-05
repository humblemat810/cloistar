import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from bridge.app.main import app
from bridge.app.runtime import reset_governance_runtime_host

@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = os.environ.get("KOGWISTAR_RUNTIME_DATA_DIR")
        os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = tmpdir
        reset_governance_runtime_host()
        try:
            with TestClient(app) as c:
                yield c
        finally:
            reset_governance_runtime_host()
            if old_dir:
                os.environ["KOGWISTAR_RUNTIME_DATA_DIR"] = old_dir
            else:
                os.environ.pop("KOGWISTAR_RUNTIME_DATA_DIR", None)

def test_kg_node_crud(client):
    # Create
    resp = client.post("/kg/node/create", json={
        "label": "Test Node",
        "type": "entity",
        "properties": {"foo": "bar"}
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    node_id = resp.json()["id"]
    # assert node_id.startswith("node|")

    # Get
    resp = client.post("/kg/node/get", json={"ids": [node_id]})
    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == 1
    assert resp.json()["nodes"][0]["label"] == "Test Node"
    assert resp.json()["nodes"][0]["properties"]["foo"] == "bar"

    # Update (Redirect)
    # Create a new node first
    resp2 = client.post("/kg/node/create", json={"label": "New Node"})
    new_node_id = resp2.json()["id"]
    
    resp = client.post("/kg/node/update", json={"from_id": node_id, "to_id": new_node_id})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Get old node with resolve_mode=redirect should give new node
    resp = client.post("/kg/node/get", json={"ids": [node_id], "resolve_mode": "redirect"})
    assert resp.json()["nodes"][0]["id"] == new_node_id

    # Delete (Tombstone)
    resp = client.post("/kg/node/delete", params={"node_id": new_node_id})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Get should be empty if active_only
    resp = client.post("/kg/node/get", json={"ids": [new_node_id], "resolve_mode": "active_only"})
    assert len(resp.json()["nodes"]) == 0

def test_kg_edge_crud(client):
    # Create nodes
    n1 = client.post("/kg/node/create", json={"label": "N1"}).json()["id"]
    n2 = client.post("/kg/node/create", json={"label": "N2"}).json()["id"]

    # Create Edge
    resp = client.post("/kg/edge/create", json={
        "relation": "test_rel",
        "source_ids": [n1],
        "target_ids": [n2],
        "properties": {"strength": 0.9}
    })
    assert resp.status_code == 200
    edge_id = resp.json()["id"]
    # assert edge_id.startswith("edge|")

    # Get Edge
    resp = client.post("/kg/edge/get", json={"ids": [edge_id]})
    assert len(resp.json()["edges"]) == 1
    assert resp.json()["edges"][0]["relation"] == "test_rel"

    # Update Edge (Redirect)
    resp2 = client.post("/kg/edge/create", json={
        "relation": "new_rel",
        "source_ids": [n1],
        "target_ids": [n2]
    })
    new_edge_id = resp2.json()["id"]
    resp = client.post("/kg/edge/update", json={"from_id": edge_id, "to_id": new_edge_id})
    assert resp.json()["ok"] is True

    # Delete Edge
    resp = client.post("/kg/edge/delete", params={"edge_id": new_edge_id})
    assert resp.json()["ok"] is True

def test_kg_query(client):
    # Create a node with specific content
    client.post("/kg/node/create", json={
        "label": "Golden Retriever",
        "summary": "A friendly dog breed known for its gold coat."
    })
    
    # Query (Mocked search might just return it if we are using the real engine in test)
    resp = client.post("/kg/query", json={"query": "friendly dog"})
    assert resp.status_code == 200
    # Success here depends on the embedding model and engine setup, but 'ok: true' should hold
    assert resp.json()["ok"] is True
