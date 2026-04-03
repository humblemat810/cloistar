from __future__ import annotations

"""Launcher that starts the bridge with demo approval tracing enabled."""

import argparse
import os
from pathlib import Path

import uvicorn

from .approval_probe import (
    DEMO_APPROVAL_PROBE_ENV,
    DEMO_APPROVAL_TRACE_FILE_ENV,
    install_demo_probe,
)


def _default_trace_path() -> str:
    state_dir = os.getenv("OPENCLAW_STATE_DIR")
    if state_dir:
        return str(Path(state_dir).parent / "logs" / "demo-approval-trace.jsonl")
    return str(Path.cwd() / "demo-approval-trace.jsonl")


def main() -> None:
    """Start the bridge under the demo approval probe."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--app", default="bridge.app.main:app")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    os.environ.setdefault(DEMO_APPROVAL_PROBE_ENV, "1")
    os.environ.setdefault(DEMO_APPROVAL_TRACE_FILE_ENV, _default_trace_path())
    install_demo_probe()
    uvicorn.run(args.app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()

