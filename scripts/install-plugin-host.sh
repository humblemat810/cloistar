#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PLUGIN_DIR="$ROOT_DIR/plugin"
PLUGIN_ID="kogwistar-governance"

openclaw plugins install -l "$PLUGIN_DIR"
openclaw plugins enable "$PLUGIN_ID"
openclaw plugins inspect "$PLUGIN_ID" >/dev/null
openclaw gateway restart
