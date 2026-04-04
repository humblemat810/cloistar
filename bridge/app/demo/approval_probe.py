from __future__ import annotations

"""Demo-only approval tracing built on ``sys.monitoring``.

This module intentionally avoids inline instrumentation in bridge business logic.
The probe is installed before the FastAPI app is imported, and it narrows itself
to a small allowlist of approval-related functions plus a few catch/error lines.
"""

from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import sys
from types import CodeType
from typing import Any

DEMO_APPROVAL_PROBE_ENV = "DEMO_APPROVAL_PROBE"
DEMO_APPROVAL_TRACE_FILE_ENV = "DEMO_APPROVAL_TRACE_FILE"
TRACE_KIND = "demo_probe"


@dataclass(frozen=True)
class ProbeTarget:
    """High-signal function probe with optional start/return events."""

    event_on_start: str | None = None
    event_on_return: str | None = None


@dataclass(frozen=True)
class LineProbe:
    """Specific line probe used for catch branches and hidden transitions."""

    line_no: int
    event: str
    stage: str


class DemoTraceWriter:
    """Simple NDJSON writer for demo probe records."""

    def __init__(self, trace_path: Path) -> None:
        self.trace_path = trace_path
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: dict[str, Any]) -> None:
        row = {
            "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "kind": TRACE_KIND,
            **record,
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str))
            handle.write("\n")


_WRITER: DemoTraceWriter | None = None
_TOOL_ID: int | None = None
_INSTALLED = False
_TARGETS_BY_CODE: dict[CodeType, ProbeTarget] = {}
_LINE_PROBES_BY_CODE: dict[CodeType, dict[int, LineProbe]] = {}


def install_demo_probe() -> bool:
    """Install the demo approval probe when explicitly enabled."""

    global _INSTALLED, _TOOL_ID, _WRITER, _TARGETS_BY_CODE, _LINE_PROBES_BY_CODE

    if _INSTALLED or not _env_enabled():
        return False
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        return False

    _WRITER = DemoTraceWriter(_resolve_trace_path())
    _TOOL_ID = _reserve_tool_id("bridge-demo-approval-probe")
    if _TOOL_ID is None:
        return False

    _TARGETS_BY_CODE, _LINE_PROBES_BY_CODE = _build_probe_tables()
    monitoring.register_callback(_TOOL_ID, monitoring.events.PY_START, _on_py_start)
    monitoring.register_callback(_TOOL_ID, monitoring.events.PY_RETURN, _on_py_return)
    monitoring.register_callback(_TOOL_ID, monitoring.events.LINE, _on_line)
    monitoring.register_callback(_TOOL_ID, monitoring.events.RAISE, _on_raise)
    monitoring.set_events(
        _TOOL_ID,
        monitoring.events.PY_START | monitoring.events.PY_RETURN | monitoring.events.RAISE,
    )
    for code in _LINE_PROBES_BY_CODE:
        monitoring.set_local_events(_TOOL_ID, code, monitoring.events.LINE)

    _INSTALLED = True
    _emit({"event": "probe.installed", "module": __name__, "function": "install_demo_probe"})
    return True


def _build_probe_tables() -> tuple[dict[CodeType, ProbeTarget], dict[CodeType, dict[int, LineProbe]]]:
    from bridge.app import main as bridge_main
    from bridge.app.runtime.governance_runtime import GovernanceRuntimeHost
    from bridge.app.store import PersistentGovernanceStore

    targets: dict[CodeType, ProbeTarget] = {
        bridge_main.before_tool_call.__code__: ProbeTarget(event_on_start="before_tool_call.enter", event_on_return="policy.decision"),
        bridge_main.approval_resolution.__code__: ProbeTarget(event_on_start="approval.resolution.enter", event_on_return="approval.resolution.completed"),
        bridge_main._apply_approval_resolution_payload.__code__: ProbeTarget(
            event_on_start="approval.resolution.apply.enter",
            event_on_return="approval.resolution.apply.completed",
        ),
        bridge_main.after_tool_call.__code__: ProbeTarget(event_on_start="after_tool_call.enter", event_on_return="tool.completed"),
        PersistentGovernanceStore.register_approval_request.__code__: ProbeTarget(event_on_return="approval.requested"),
        PersistentGovernanceStore.resolve_approval.__code__: ProbeTarget(event_on_return="approval.resolved.store"),
        PersistentGovernanceStore.register_gateway_approval.__code__: ProbeTarget(event_on_return="gateway.approval.requested"),
        PersistentGovernanceStore.resolve_gateway_approval.__code__: ProbeTarget(event_on_return="gateway.approval.resolved"),
        GovernanceRuntimeHost.evaluate_proposal.__code__: ProbeTarget(event_on_return="runtime.decision.completed"),
        GovernanceRuntimeHost.resume_approval.__code__: ProbeTarget(event_on_return="runtime.resume.completed"),
    }
    line_probes: dict[CodeType, dict[int, LineProbe]] = {
        bridge_main.before_tool_call.__code__: {
            _find_line(bridge_main.before_tool_call, "evaluation = decide("): LineProbe(
                line_no=_find_line(bridge_main.before_tool_call, "evaluation = decide("),
                event="error.caught",
                stage="before_tool_call.runtime_fallback",
            ),
            _find_line(bridge_main.before_tool_call, "append_event(store, suspended_event)"): LineProbe(
                line_no=_find_line(bridge_main.before_tool_call, "append_event(store, suspended_event)"),
                event="execution.suspended",
                stage="before_tool_call.require_approval",
            ),
        },
        bridge_main._apply_approval_resolution_payload.__code__: {
            _find_line(bridge_main._apply_approval_resolution_payload, "updated = append_approval_resolution("): LineProbe(
                line_no=_find_line(bridge_main._apply_approval_resolution_payload, "updated = append_approval_resolution("),
                event="approval.resolution.received",
                stage="approval_resolution.append",
            ),
            _find_line(bridge_main._apply_approval_resolution_payload, '{"resumeError": str(exc)},'): LineProbe(
                line_no=_find_line(bridge_main._apply_approval_resolution_payload, '{"resumeError": str(exc)},'),
                event="error.caught",
                stage="approval_resolution.resume_error",
            ),
        },
        bridge_main.after_tool_call.__code__: {
            _find_line(bridge_main.after_tool_call, '{"completionProjectionError": str(exc)},'): LineProbe(
                line_no=_find_line(bridge_main.after_tool_call, '{"completionProjectionError": str(exc)},'),
                event="error.caught",
                stage="after_tool_call.completion_projection_error",
            ),
        },
    }
    return targets, line_probes


def _on_py_start(code: CodeType, _offset: int) -> None:
    target = _TARGETS_BY_CODE.get(code)
    if target is None or target.event_on_start is None:
        return
    frame = _target_frame()
    _emit(
        {
            "event": target.event_on_start,
            "module": code.co_filename,
            "function": code.co_name,
            **_extract_common_fields(frame),
        }
    )


def _on_py_return(code: CodeType, _offset: int, return_value: Any) -> None:
    target = _TARGETS_BY_CODE.get(code)
    if target is None or target.event_on_return is None:
        return
    frame = _target_frame()
    payload = {
        "event": target.event_on_return,
        "module": code.co_filename,
        "function": code.co_name,
        **_extract_common_fields(frame),
        **_extract_from_value(return_value),
    }

    if code.co_name == "before_tool_call":
        decision = _decision_from_value(return_value)
        if decision == "allow":
            payload["event"] = "policy.decision.allow"
        elif decision == "block":
            payload["event"] = "policy.decision.block"
        elif decision == "requireApproval":
            payload["event"] = "policy.decision.require_approval"
        payload["disposition"] = decision
    elif code.co_name == "resume_approval":
        workflow = return_value.workflow if return_value is not None else None
        if isinstance(workflow, dict):
            payload.update(_extract_from_value(workflow))
            disposition = workflow.get("finalDisposition")
            if disposition == "deny":
                payload["event"] = "execution.denied"
            else:
                payload["event"] = "execution.resumed"
    elif code.co_name == "after_tool_call" and frame is not None:
        completed_event = frame.f_locals.get("completed_event")
        payload.update(_extract_from_value(completed_event))
    _emit(payload)


def _on_line(code: CodeType, line_no: int) -> None:
    probes = _LINE_PROBES_BY_CODE.get(code)
    if probes is None:
        return
    probe = probes.get(line_no)
    if probe is None:
        return
    frame = _target_frame()
    payload = {
        "event": probe.event,
        "module": code.co_filename,
        "function": code.co_name,
        "lineno": line_no,
        "stage": probe.stage,
        **_extract_common_fields(frame),
    }
    if frame is not None:
        payload["locals"] = _interesting_locals(frame)
    _emit(payload)


def _on_raise(code: CodeType, line_no: int, error: BaseException) -> None:
    if code not in _TARGETS_BY_CODE:
        return
    frame = _target_frame()
    _emit(
        {
            "event": "error.raised",
            "module": code.co_filename,
            "function": code.co_name,
            "lineno": line_no,
            "errorType": type(error).__name__,
            "error": str(error),
            **_extract_common_fields(frame),
        }
    )


def _decision_from_value(value: Any) -> str | None:
    if isinstance(value, dict):
        decision = value.get("decision")
        return decision if isinstance(decision, str) else None
    return None


def _extract_common_fields(frame) -> dict[str, Any]:
    if frame is None:
        return {}
    extracted: dict[str, Any] = {}
    for local_name in ("payload", "approval_row", "approval", "observed_event", "resolved_event", "completed_event"):
        extracted.update(_extract_from_value(frame.f_locals.get(local_name)))
    for local_name, output_name in (
        ("governance_call_id", "governanceCallId"),
        ("run_id", "runId"),
        ("resolution", "resolution"),
    ):
        value = frame.f_locals.get(local_name)
        if isinstance(value, str) and value:
            extracted[output_name] = value
    return extracted


def _extract_from_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return {}

    extracted: dict[str, Any] = {}
    mappings = (
        ("governanceCallId", "governanceCallId"),
        ("approvalRequestId", "approvalRequestId"),
        ("gatewayApprovalId", "gatewayApprovalId"),
        ("toolCallId", "toolCallId"),
        ("runId", "runId"),
        ("sessionId", "sessionId"),
        ("toolName", "toolName"),
        ("decision", "disposition"),
        ("approvalResolution", "resolution"),
        ("finalDisposition", "disposition"),
    )
    for source, target in mappings:
        found = _lookup_nested(value, source)
        if isinstance(found, (str, int, float, bool)) or found is None:
            if found is not None:
                extracted[target] = found
    return extracted


def _lookup_nested(value: dict[str, Any], key: str) -> Any:
    if key in value:
        return value[key]
    for nested_key in ("subject", "data", "request", "projection", "workflow"):
        nested = value.get(nested_key)
        if isinstance(nested, dict) and key in nested:
            return nested[key]
    if key == "toolName":
        tool = value.get("tool")
        if isinstance(tool, dict):
            return tool.get("name")
    if key == "toolCallId":
        data = value.get("data")
        if isinstance(data, dict):
            execution_context = data.get("executionContext")
            if isinstance(execution_context, dict):
                return execution_context.get("toolCallId")
    return None


def _interesting_locals(frame) -> dict[str, Any]:
    interesting: dict[str, Any] = {}
    for key in ("evaluation", "resolved_event", "suspended_event", "exc"):
        value = frame.f_locals.get(key)
        if value is not None:
            interesting[key] = str(value)
    return interesting


def _target_frame():
    try:
        return sys._getframe(1)
    except ValueError:
        return None


def _emit(record: dict[str, Any]) -> None:
    if _WRITER is None:
        return
    _WRITER.emit(record)


def _env_enabled() -> bool:
    return os.getenv(DEMO_APPROVAL_PROBE_ENV) == "1"


def _resolve_trace_path() -> Path:
    configured = os.getenv(DEMO_APPROVAL_TRACE_FILE_ENV)
    if configured:
        return Path(configured)
    state_dir = os.getenv("OPENCLAW_STATE_DIR")
    if state_dir:
        return Path(state_dir).parent / "logs" / "demo-approval-trace.jsonl"
    return Path.cwd() / "demo-approval-trace.jsonl"


def _reserve_tool_id(name: str) -> int | None:
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        return None
    for tool_id in range(5, -1, -1):
        try:
            monitoring.use_tool_id(tool_id, name)
            return tool_id
        except ValueError:
            continue
    return None


def _find_line(func: Any, snippet: str) -> int:
    source_lines, start_line = inspect.getsourcelines(func)
    matches = [
        start_line + index
        for index, line in enumerate(source_lines)
        if snippet in line
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one match for {snippet!r} in {func.__qualname__}")
    return matches[0]
