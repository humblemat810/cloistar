#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PLUGIN_DIR="$ROOT_DIR/plugin"
PLUGIN_ID="kogwistar-governance"
OPENCLAW_BIN="${OPENCLAW_BIN:-$(command -v openclaw 2>/dev/null || true)}"

if [[ -z "$OPENCLAW_BIN" ]]; then
  echo "Missing OpenClaw CLI: set OPENCLAW_BIN or install 'openclaw' so it is on PATH." >&2
  exit 1
fi

"$OPENCLAW_BIN" plugins install -l "$PLUGIN_DIR"
"$OPENCLAW_BIN" plugins enable "$PLUGIN_ID"
"$OPENCLAW_BIN" plugins inspect "$PLUGIN_ID" >/dev/null
"$OPENCLAW_BIN" gateway restart
