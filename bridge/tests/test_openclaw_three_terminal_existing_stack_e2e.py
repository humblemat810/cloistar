from __future__ import annotations

"""Live three-terminal OpenClaw governance E2E cases against an existing stack.

This variant assumes the helper has already been started separately, typically
with a stable run directory, and only launches the agent + approver
subprocesses. It complements the self-starting harness tests by validating that
the same three-terminal flow works when the bridge/gateway/OpenClaw runtime
already exist.

Required environment for these tests:

- ``OPENCLAW_RUN_E2E=1``
- ``OPENCLAW_RUN_EXISTING_STACK_E2E=1``
- ``OPENCLAW_EXISTING_BRIDGE_URL=http://127.0.0.1:<port>``
- ``OPENCLAW_EXISTING_RUN_DIR=/path/to/run-dir``

Run it with:

```bash
OPENCLAW_RUN_E2E=1 \
OPENCLAW_RUN_EXISTING_STACK_E2E=1 \
OPENCLAW_EXISTING_BRIDGE_URL=http://127.0.0.1:<bridge-port> \
OPENCLAW_EXISTING_RUN_DIR=/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_existing_stack_e2e.py -q
```

Optional:

- ``OPENCLAW_EXISTING_GATEWAY_URL=http://127.0.0.1:<port>``
- ``OPENCLAW_E2E_OLLAMA_MODEL=qwen3:4b``
"""

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
HARNESS = ROOT_DIR / "scripts" / "run-openclaw-governance-three-terminal.py"
PYTHON = ROOT_DIR / ".venv" / "bin" / "python"

pytestmark = [pytest.mark.e2e]


def _attached_e2e_enabled() -> bool:
    return os.getenv("OPENCLAW_RUN_E2E") == "1" and os.getenv("OPENCLAW_RUN_EXISTING_STACK_E2E") == "1"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"Set {name} for attached-stack OpenClaw E2E tests")
    return value


@pytest.mark.skipif(
    not _attached_e2e_enabled(),
    reason="Set OPENCLAW_RUN_E2E=1 and OPENCLAW_RUN_EXISTING_STACK_E2E=1 to run attached-stack OpenClaw E2E tests",
)
@pytest.mark.parametrize(
    ("demo_case", "approval_mode"),
    [
        ("allow", "auto-allow"),
        ("block", "auto-allow"),
        ("approval", "auto-allow"),
        ("approval", "llm"),
    ],
)
def test_openclaw_three_terminal_existing_stack_e2e(
    tmp_path: Path,
    demo_case: str,
    approval_mode: str,
) -> None:
    summary_path = tmp_path / f"existing-{demo_case}-{approval_mode}-summary.json"
    bridge_url = _required_env("OPENCLAW_EXISTING_BRIDGE_URL")
    run_dir = _required_env("OPENCLAW_EXISTING_RUN_DIR")
    gateway_url = os.getenv("OPENCLAW_EXISTING_GATEWAY_URL")
    ollama_model = os.getenv("OPENCLAW_E2E_OLLAMA_MODEL", "qwen3:4b")

    command = [
        str(PYTHON),
        str(HARNESS),
        "--use-existing-stack",
        "--bridge-url",
        bridge_url,
        "--run-dir",
        run_dir,
        "--demo-case",
        demo_case,
        "--approval-mode",
        approval_mode,
        "--ollama-model",
        ollama_model,
        "--summary-json",
        str(summary_path),
        "--agent-timeout",
        "420",
    ]
    if gateway_url:
        command.extend(["--gateway-url", gateway_url])

    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )

    assert summary_path.exists(), f"missing summary file\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    summary = json.loads(summary_path.read_text())

    assert result.returncode == 0, (
        f"attached-stack harness failed for {demo_case}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\n"
        f"summary:\n{json.dumps(summary, indent=2)}"
    )
    assert summary["ok"] is True
    assert summary["demoCase"] == demo_case
    assert summary["approvalMode"] == approval_mode
    assert summary["bridgeUrl"].rstrip("/") == bridge_url.rstrip("/")
    assert summary["runDir"] == run_dir

    event_types = [event["eventType"] for event in summary["events"]]
    if demo_case == "allow":
        assert "governance.tool_call_completed.v1" in event_types
    elif demo_case == "block":
        decision_events = [event for event in summary["events"] if event["eventType"] == "governance.decision_recorded.v1"]
        assert decision_events
        assert decision_events[-1]["data"]["disposition"] == "block"
    else:
        assert "governance.approval_resolved.v1" in event_types
        assert "governance.execution_resumed.v1" in event_types
        assert summary["execApprovalIds"], "expected downstream exec approvals during live approval flow"
