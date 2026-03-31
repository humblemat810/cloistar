#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
DEFAULT_OPENCLAW_REPO_DIR="$ROOT_DIR/openclaw"
OPENCLAW_REPO_DIR="${OPENCLAW_REPO_DIR:-$DEFAULT_OPENCLAW_REPO_DIR}"
PLUGIN_DIR="$ROOT_DIR/plugin"
PLUGIN_ID="kogwistar-governance"

if [[ ! -d "$OPENCLAW_REPO_DIR" || ! -f "$OPENCLAW_REPO_DIR/openclaw.mjs" ]]; then
  if [[ -d "$DEFAULT_OPENCLAW_REPO_DIR" && -f "$DEFAULT_OPENCLAW_REPO_DIR/openclaw.mjs" ]]; then
    echo "OPENCLAW_REPO_DIR=$OPENCLAW_REPO_DIR does not look like an OpenClaw checkout; using $DEFAULT_OPENCLAW_REPO_DIR instead." >&2
    OPENCLAW_REPO_DIR="$DEFAULT_OPENCLAW_REPO_DIR"
  else
    echo "Missing OpenClaw repo checkout: expected $DEFAULT_OPENCLAW_REPO_DIR or a valid OPENCLAW_REPO_DIR" >&2
    exit 1
  fi
fi

if [[ ! -f "$OPENCLAW_REPO_DIR/openclaw.mjs" ]]; then
  echo "Invalid OpenClaw checkout: missing $OPENCLAW_REPO_DIR/openclaw.mjs" >&2
  exit 1
fi

cd "$OPENCLAW_REPO_DIR"
node openclaw.mjs plugins install -l "$PLUGIN_DIR"
node openclaw.mjs plugins enable "$PLUGIN_ID"
node openclaw.mjs plugins inspect "$PLUGIN_ID" >/dev/null
node openclaw.mjs gateway restart
