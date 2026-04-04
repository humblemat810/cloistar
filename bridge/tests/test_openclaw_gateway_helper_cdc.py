from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import urllib.request

from bridge.app.runtime.governance_graph import governance_node
from bridge.app.runtime.governance_runtime import _ZERO_EMBEDDING_FUNCTION
from kogwistar.engine_core.engine import GraphKnowledgeEngine
from kogwistar.utils.kge_debug_dump import dump_paired_bundles


ROOT_DIR = Path(__file__).resolve().parents[2]
HELPER = ROOT_DIR / "scripts" / "run-openclaw-gateway-governance-e2e.sh"
TEMPLATE = ROOT_DIR / "kogwistar" / "kogwistar" / "templates" / "d3.html"


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http_ok(url: str, *, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 300:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"{url} did not become healthy in time: {last_error!r}")


def _count_cdc_oplog_entries(oplog_file: Path) -> int:
    if not oplog_file.exists():
        return 0
    with oplog_file.open("r", encoding="utf-8") as fh:
        line_count = sum(1 for line in fh if line.strip())
    return max(0, line_count - 1)


def _wait_for_cdc_entries(oplog_file: Path, *, min_entries: int = 1, timeout_s: float = 20.0) -> int:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        entry_count = _count_cdc_oplog_entries(oplog_file)
        if entry_count >= min_entries:
            return entry_count
        time.sleep(0.1)
    raise AssertionError(f"CDC oplog did not record {min_entries} entries in time: {oplog_file}")


def test_helper_help_includes_demo_cdc() -> None:
    result = subprocess.run(
        ["bash", str(HELPER), "--help"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--demo-cdc" in result.stdout


def test_helper_rejects_demo_cdc_with_existing_bridge() -> None:
    result = subprocess.run(
        ["bash", str(HELPER), "--demo-cdc", "--use-existing-bridge"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    assert "--demo-cdc is not supported with --use-existing-bridge" in result.stderr


def test_empty_cdc_page_render_succeeds_without_embeddings(tmp_path: Path) -> None:
    out_dir = tmp_path / "cdc-pages"
    ws_url = "ws://127.0.0.1:8787/changes/ws"

    meta = dump_paired_bundles(
        kg_engine=None,
        conversation_engine=None,
        workflow_engine=None,
        template_html=TEMPLATE.read_text(encoding="utf-8"),
        out_dir=out_dir,
        cdc_ws_url=ws_url,
        embed_empty=True,
    )

    workflow_html = (out_dir / "workflow.bundle.html").read_text(encoding="utf-8")
    conversation_html = (out_dir / "conversation.bundle.html").read_text(encoding="utf-8")
    assert meta["conversation_bundle_href"] == "./conversation.bundle.html"
    assert ws_url in workflow_html
    assert ws_url in conversation_html
    assert "{{" not in workflow_html and "{%" not in workflow_html
    assert "{{" not in conversation_html and "{%" not in conversation_html


def test_cdc_publish_endpoint_base_url_delivers_graph_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = _pick_free_port()
    host = "127.0.0.1"
    endpoint = f"http://{host}:{port}"
    oplog_file = tmp_path / "cdc_oplog.jsonl"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kogwistar.cdc.change_bridge",
            "--host",
            host,
            "--port",
            str(port),
            "--oplog-file",
            str(oplog_file),
            "--reset-oplog",
            "--log-level",
            "warning",
        ],
        cwd=ROOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_http_ok(f"{endpoint}/openapi.json")
        monkeypatch.setenv("CDC_PUBLISH_ENDPOINT", endpoint)
        engine = GraphKnowledgeEngine(
            persist_directory=str(tmp_path / "conversation"),
            kg_graph_type="conversation",
            embedding_function=_ZERO_EMBEDDING_FUNCTION,
        )
        node = governance_node(
            node_id="gov|cdc|n1",
            label="proposal",
            summary="cdc smoke node",
            doc_id="doc:cdc:1",
            metadata={
                "entity_type": "governance_proposal",
                "governance_call_id": "cdc-smoke",
            },
        )
        engine.write.add_node(node)

        assert _wait_for_cdc_entries(oplog_file, min_entries=1) >= 1
        payload_lines = [json.loads(line) for line in oplog_file.read_text(encoding="utf-8").splitlines()[1:] if line.strip()]
        assert payload_lines
        assert payload_lines[-1]["entity"]["id"] == "gov|cdc|n1"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15.0)
