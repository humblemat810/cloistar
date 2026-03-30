#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PLUGIN_DIR="$ROOT_DIR/plugin"

openclaw plugins install -l "$PLUGIN_DIR"
openclaw gateway restart