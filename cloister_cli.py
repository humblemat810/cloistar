from __future__ import annotations

import argparse
import json
from pathlib import Path

from cloister_openclaw_install import run_openclaw_install


def _print_quickstart_summary(summary: dict[str, object]) -> None:
    artifacts = dict(summary.get("artifacts") or {})
    print(f"Answer: {summary.get('answer_text', '')}")
    print(f"Replay: {'pass' if summary.get('replay_pass') else 'fail'}")
    print(f"Provenance Artifact: {artifacts.get('provenance_html', '')}")
    print(f"Graph Artifact: {artifacts.get('graph_html', '')}")
    print(f"Replay Report: {artifacts.get('replay_json', '')}")
    print(f"Next: {summary.get('next_command', '')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloister",
        description="Provenance-first, replayable AI workflow tooling.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_demo_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--data-dir", default=".gke-data/quickstart")
        target.add_argument(
            "--question",
            default="How does Kogwistar make AI workflows replayable and auditable?",
        )
        target.add_argument(
            "--open-browser",
            action=argparse.BooleanOptionalAction,
            default=False,
        )
        target.add_argument("--json", action="store_true")

    quickstart = sub.add_parser(
        "quickstart",
        help="Run the deterministic provenance-first demo.",
    )
    _add_demo_args(quickstart)

    serve = sub.add_parser(
        "serve", help="Start the existing MCP/server surface."
    )
    serve.add_argument(
        "--data-dir",
        default=None,
        help="Reserved for future use; server storage remains env-driven.",
    )

    install = sub.add_parser(
        "install-openclaw",
        help="Detect OpenClaw and prepare either integrated or client-only governance setup.",
    )
    install.add_argument(
        "--bridge-url",
        default=None,
        help="Override the governance bridge URL used for client-side mode.",
    )
    install.add_argument(
        "--openclaw-home",
        default=None,
        help="Set the OpenClaw home directory explicitly.",
    )
    install.add_argument(
        "--openclaw-repo",
        default=None,
        help="Set the OpenClaw repository path explicitly.",
    )
    install.add_argument(
        "--openclaw-cli",
        default=None,
        help="Set the OpenClaw CLI binary explicitly.",
    )
    install.add_argument(
        "--no-write-config",
        action="store_true",
        help="Only print detection and commands without writing the local client config.",
    )

    demo = sub.add_parser("demo", help="Run named demos.")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    provenance = demo_sub.add_parser(
        "provenance", help="Run the provenance-first signature demo."
    )
    _add_demo_args(provenance)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        from kogwistar.server_mcp_with_admin import main as serve_main

        serve_main()
        return 0

    if args.command == "install-openclaw":
        return run_openclaw_install(
            bridge_url=args.bridge_url,
            openclaw_home=args.openclaw_home,
            openclaw_repo=args.openclaw_repo,
            openclaw_cli=args.openclaw_cli,
            write_config=not bool(args.no_write_config),
        )

    if args.command == "quickstart" or (
        args.command == "demo" and args.demo_command == "provenance"
    ):
        from kogwistar.demo import run_provenance_quickstart

        summary = run_provenance_quickstart(
            data_dir=Path(args.data_dir),
            question=str(args.question),
            open_browser=bool(args.open_browser),
        )
        if args.json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            _print_quickstart_summary(summary)
        return 0

    parser.error("Unknown command")
    return 2
