from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenClawInstallState:
    openclaw_home: str | None
    openclaw_repo: str | None
    openclaw_cli: str | None
    npx_cli: str | None
    node_cli: str | None
    openclaw_detected: bool
    bridge_url: str
    plugin_governance_path: str | None
    plugin_kg_path: str | None
    client_mode_config: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _default_config_dir() -> Path:
    base = os.getenv("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "cloister"
    return Path.home() / ".config" / "cloister"


def _default_client_config_path() -> Path:
    return _default_config_dir() / "openclaw-client.json"


def _detect_cli(name: str) -> str | None:
    return shutil.which(name)


def _first_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_openclaw_repo(
    openclaw_repo: str | None = None, openclaw_home: str | None = None
) -> Path | None:
    candidates: list[Path] = []
    if openclaw_repo:
        candidates.append(Path(openclaw_repo).expanduser())
    if openclaw_home:
        home = Path(openclaw_home).expanduser()
        candidates.extend([home, home / "openclaw"])
    env_repo = os.getenv("OPENCLAW_REPO")
    if env_repo:
        candidates.append(Path(env_repo).expanduser())
    env_home = os.getenv("OPENCLAW_HOME")
    if env_home:
        home = Path(env_home).expanduser()
        candidates.extend([home, home / "openclaw"])
    default_home = Path.home() / "cloistar" / "openclaw"
    candidates.extend([default_home, default_home / "openclaw"])
    return _first_existing_path(candidates)


def detect_openclaw_state(
    *,
    bridge_url: str | None = None,
    openclaw_home: str | None = None,
    openclaw_repo: str | None = None,
    openclaw_cli: str | None = None,
) -> OpenClawInstallState:
    repo_root = _repo_root()
    openclaw_cli = openclaw_cli or os.getenv("OPENCLAW_CLI") or _detect_cli("openclaw")
    npx_cli = _detect_cli("npx")
    node_cli = _detect_cli("node")
    bridge_url = bridge_url or os.getenv("KOGWISTAR_BRIDGE_URL") or "http://127.0.0.1:8799"
    plugin_governance_path = repo_root / "plugin-governance"
    plugin_kg_path = repo_root / "plugin-kg"
    resolved_repo = _resolve_openclaw_repo(openclaw_repo=openclaw_repo, openclaw_home=openclaw_home)
    resolved_home: str | None
    if openclaw_home is not None:
        resolved_home = str(Path(openclaw_home).expanduser())
    else:
        env_home = os.getenv("OPENCLAW_HOME")
        resolved_home = env_home if env_home else None
        if resolved_home is None and resolved_repo is not None:
            resolved_home = str(resolved_repo.parent if resolved_repo.name == "openclaw" else resolved_repo)
    return OpenClawInstallState(
        openclaw_home=resolved_home,
        openclaw_repo=str(resolved_repo) if resolved_repo is not None else None,
        openclaw_cli=openclaw_cli,
        npx_cli=npx_cli,
        node_cli=node_cli,
        openclaw_detected=openclaw_cli is not None or resolved_repo is not None,
        bridge_url=bridge_url,
        plugin_governance_path=str(plugin_governance_path) if plugin_governance_path.exists() else None,
        plugin_kg_path=str(plugin_kg_path) if plugin_kg_path.exists() else None,
        client_mode_config=str(_default_client_config_path()),
    )


def _plugin_install_commands(state: OpenClawInstallState) -> list[str]:
    if state.openclaw_cli:
        if state.openclaw_repo:
            return [
                f"cd {state.openclaw_repo} && {state.openclaw_cli} extension add {state.plugin_governance_path or './plugin-governance'}",
                f"cd {state.openclaw_repo} && {state.openclaw_cli} extension add {state.plugin_kg_path or './plugin-kg'}",
            ]
        return [
            f"{state.openclaw_cli} extension add ./plugin-governance",
            f"{state.openclaw_cli} extension add ./plugin-kg",
        ]
    if state.npx_cli:
        return [
            "npx openclaw extension add ./plugin-governance",
            "npx openclaw extension add ./plugin-kg",
        ]
    return []


def ensure_client_mode_config(
    *,
    bridge_url: str | None = None,
    openclaw_home: str | None = None,
    openclaw_repo: str | None = None,
    openclaw_cli: str | None = None,
    overwrite: bool = False,
) -> tuple[Path, dict[str, Any]]:
    state = detect_openclaw_state(
        bridge_url=bridge_url,
        openclaw_home=openclaw_home,
        openclaw_repo=openclaw_repo,
        openclaw_cli=openclaw_cli,
    )
    config_path = Path(state.client_mode_config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "bridge_url": state.bridge_url,
        "mode": "client-side-governance",
        "openclaw_home": state.openclaw_home,
        "openclaw_repo": state.openclaw_repo,
        "openclaw_detected": state.openclaw_detected,
        "openclaw_cli": state.openclaw_cli,
        "npx_cli": state.npx_cli,
        "node_cli": state.node_cli,
        "plugin_governance_path": state.plugin_governance_path,
        "plugin_kg_path": state.plugin_kg_path,
        "plugin_install_commands": _plugin_install_commands(state),
    }
    if overwrite or not config_path.exists():
        config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return config_path, payload


def print_install_summary(state: OpenClawInstallState) -> None:
    print("OpenClaw detection:")
    print(f"  openclaw_home: {state.openclaw_home or 'not set'}")
    print(f"  openclaw_repo: {state.openclaw_repo or 'not found'}")
    print(f"  openclaw: {state.openclaw_cli or 'not found'}")
    print(f"  npx: {state.npx_cli or 'not found'}")
    print(f"  node: {state.node_cli or 'not found'}")
    print(f"  bridge_url: {state.bridge_url}")
    print(f"  client_mode_config: {state.client_mode_config}")

    commands = _plugin_install_commands(state)
    if commands:
        print("Plugin install commands:")
        for command in commands:
            print(f"  {command}")
    else:
        print(
            "OpenClaw was not detected, so this install will stay in client-side-only "
            "governance mode until you add OpenClaw."
        )


def run_openclaw_install(
    *,
    bridge_url: str | None = None,
    openclaw_home: str | None = None,
    openclaw_repo: str | None = None,
    openclaw_cli: str | None = None,
    write_config: bool = True,
) -> int:
    state = detect_openclaw_state(
        bridge_url=bridge_url,
        openclaw_home=openclaw_home,
        openclaw_repo=openclaw_repo,
        openclaw_cli=openclaw_cli,
    )
    if write_config:
        config_path, payload = ensure_client_mode_config(
            bridge_url=bridge_url,
            openclaw_home=openclaw_home,
            openclaw_repo=openclaw_repo,
            openclaw_cli=openclaw_cli,
            overwrite=True,
        )
        print(f"Wrote client governance config to {config_path}")
        if payload.get("plugin_install_commands"):
            print("Suggested OpenClaw plugin commands:")
            for command in payload["plugin_install_commands"]:
                print(f"  {command}")
    print_install_summary(state)
    return 0
