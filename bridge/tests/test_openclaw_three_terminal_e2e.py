from __future__ import annotations

"""Live three-terminal OpenClaw governance E2E cases that self-start the stack.

This file drives the subprocess harness instead of FastAPI TestClient so it can
exercise the real helper/gateway/agent boundary. Unlike the attached-stack E2E
variant, these tests start the helper themselves for each case.

Cases covered here:

- allow
- block
- approval + auto-allow
- approval + llm

Run the non-manual cases with:

```bash
OPENCLAW_RUN_E2E=1 \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_e2e.py -q
```

Manual approval is intentionally separated because it needs console input and is
only enabled when both OPENCLAW_RUN_E2E=1 and OPENCLAW_RUN_MANUAL_E2E=1.

Run the manual case with:

```bash
OPENCLAW_RUN_E2E=1 OPENCLAW_RUN_MANUAL_E2E=1 \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_e2e.py -q
```
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


def _e2e_enabled() -> bool:
    return os.getenv("OPENCLAW_RUN_E2E") == "1"


def _manual_e2e_enabled() -> bool:
    return os.getenv("OPENCLAW_RUN_MANUAL_E2E") == "1"


@pytest.mark.skipif(not _e2e_enabled(), reason="Set OPENCLAW_RUN_E2E=1 to run live OpenClaw E2E tests")
@pytest.mark.parametrize(
    ("demo_case", "approval_mode"),
    [
        ("allow", "auto-allow"),
        ("block", "auto-allow"),
        ("approval", "auto-allow"),
        ("approval", "llm"),
    ],
)
def test_openclaw_three_terminal_policy_e2e(tmp_path: Path, demo_case: str, approval_mode: str) -> None:
    summary_path = tmp_path / f"{demo_case}-{approval_mode}-summary.json"
    run_dir = tmp_path / f"run-{demo_case}-{approval_mode}"
    ollama_model = os.getenv("OPENCLAW_E2E_OLLAMA_MODEL", "qwen3:4b")

    command = [
        str(PYTHON),
        str(HARNESS),
        "--demo-case",
        demo_case,
        "--approval-mode",
        approval_mode,
        "--ollama-model",
        ollama_model,
        "--no-stable-run-dir",
        "--run-dir",
        str(run_dir),
        "--summary-json",
        str(summary_path),
        "--agent-timeout",
        "420",
    ]
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
        f"harness failed for {demo_case}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\n"
        f"summary:\n{json.dumps(summary, indent=2)}"
    )
    assert summary["ok"] is True
    assert summary["demoCase"] == demo_case
    assert summary["approvalMode"] == approval_mode

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


@pytest.mark.skipif(
    not (_e2e_enabled() and _manual_e2e_enabled()),
    reason="Set OPENCLAW_RUN_E2E=1 and OPENCLAW_RUN_MANUAL_E2E=1 to run manual console approval E2E",
)
def test_openclaw_three_terminal_policy_e2e_manual(tmp_path: Path) -> None:
    summary_path = tmp_path / "approval-manual-summary.json"
    run_dir = tmp_path / "run-approval-manual"
    ollama_model = os.getenv("OPENCLAW_E2E_OLLAMA_MODEL", "qwen3:4b")

    command = [
        str(PYTHON),
        str(HARNESS),
        "--demo-case",
        "approval",
        "--approval-mode",
        "manual",
        "--ollama-model",
        ollama_model,
        "--no-stable-run-dir",
        "--run-dir",
        str(run_dir),
        "--summary-json",
        str(summary_path),
        "--agent-timeout",
        "420",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        check=False,
        timeout=900,
    )

    assert summary_path.exists(), f"missing summary file\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    summary = json.loads(summary_path.read_text())
    assert result.returncode == 0, json.dumps(summary, indent=2)
    assert summary["ok"] is True
    assert summary["demoCase"] == "approval"
    assert summary["approvalMode"] == "manual"
