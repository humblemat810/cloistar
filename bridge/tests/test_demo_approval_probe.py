from __future__ import annotations

"""Focused tests for the demo-only approval probe helpers."""

import json

from bridge.app.demo import approval_probe


def test_install_demo_probe_is_noop_without_env(monkeypatch) -> None:
    monkeypatch.delenv(approval_probe.DEMO_APPROVAL_PROBE_ENV, raising=False)
    monkeypatch.setattr(approval_probe, "_INSTALLED", False)
    assert approval_probe.install_demo_probe() is False


def test_trace_writer_emits_ndjson(tmp_path) -> None:
    trace_path = tmp_path / "demo-approval-trace.jsonl"
    writer = approval_probe.DemoTraceWriter(trace_path)
    writer.emit({"event": "policy.decision.allow", "module": "x", "function": "y"})
    payload = json.loads(trace_path.read_text(encoding="utf-8").strip())
    assert payload["kind"] == approval_probe.TRACE_KIND
    assert payload["event"] == "policy.decision.allow"
    assert payload["module"] == "x"
    assert payload["function"] == "y"


def test_find_line_returns_unique_line_number() -> None:
    def sample() -> str:
        marker = "one"
        return marker

    assert approval_probe._find_line(sample, 'marker = "one"') > 0
