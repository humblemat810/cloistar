#!/usr/bin/env bash
set -euo pipefail

# End-to-end launcher for a local OpenClaw <-> plugin <-> bridge governance run.
#
# What this script does:
# - creates an isolated OpenClaw config/state/workspace under a timestamped run dir
# - builds the local governance plugin and installs/enables it in that isolated state
# - starts the FastAPI bridge from this repo's Python venv unless you point at an existing bridge
# - starts the local OpenClaw gateway from this repo's checkout with Node 22
# - prints the exact log/config/state paths you need to inspect correctness
# - shuts both child processes down on Ctrl-C while keeping the run artifacts on disk
#
# What this script does not guarantee by itself:
# - a successful agent turn, because that still depends on your provider/model config
# - approval resolution through a specific chat surface, because that depends on the
#   client/session you use to submit and approve the request
#
# Typical usage:
#   ./scripts/run-openclaw-gateway-governance-e2e.sh
#   ./scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model glm-4.7-flash
#   ./scripts/run-openclaw-gateway-governance-e2e.sh --message "Use the read tool (not exec) to read proof.txt and reply with the exact contents only."
#   ./scripts/run-openclaw-gateway-governance-e2e.sh --use-existing-bridge --bridge-url http://127.0.0.1:8788

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
OPENCLAW_DIR="$ROOT_DIR/openclaw"
PLUGIN_DIR="$ROOT_DIR/plugin"
BRIDGE_PYTHON="$ROOT_DIR/.venv/bin/python"
OPENCLAW_ENTRY="$OPENCLAW_DIR/openclaw.mjs"

DEFAULT_NODE_BIN="$HOME/.nvm/versions/node/v22.22.2/bin/node"
DEFAULT_NPM_CLI_JS="$HOME/.nvm/versions/node/v22.22.2/lib/node_modules/npm/bin/npm-cli.js"

NODE_BIN="${NODE_BIN:-$DEFAULT_NODE_BIN}"
NPM_CLI_JS="${NPM_CLI_JS:-$DEFAULT_NPM_CLI_JS}"
NODE_EXTRA_CA_CERTS_PATH="${NODE_EXTRA_CA_CERTS_PATH:-/etc/ssl/certs/ca-certificates.crt}"

USE_EXISTING_BRIDGE=0
BRIDGE_URL=""
BRIDGE_PORT=""
GATEWAY_PORT=""
RUN_DIR=""
STABLE_RUN_DIR=0
MESSAGE=""
SESSION_ID="governance-e2e"
DEMO_CASE=""
OLLAMA_URL=""
OLLAMA_MODEL=""
OLLAMA_API_KEY="ollama-local"
PLUGIN_INSPECT_TIMEOUT="${PLUGIN_INSPECT_TIMEOUT:-20s}"
SKIP_PLUGIN_BUILD=0
SKIP_PLUGIN_INSTALL=0
WAIT_FOREVER=1
GATEWAY_VERBOSE=1
DEMO_PROBE=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run-openclaw-gateway-governance-e2e.sh [options]

Options:
  --run-dir PATH              Keep artifacts under this directory instead of a timestamped default.
  --stable-run-dir            Reuse a stable run directory at ./.tmp/openclaw-gateway-e2e/current.
  --bridge-port PORT          Bridge port to use when starting a local bridge.
  --gateway-port PORT         Gateway port to use when starting the local OpenClaw gateway.
  --use-existing-bridge       Do not start the FastAPI bridge; use --bridge-url instead.
  --bridge-url URL            Existing bridge URL. Default with --use-existing-bridge: http://127.0.0.1:8788
  --ollama-model ID           Configure OpenClaw to use ollama/ID as the default model.
  --ollama-url URL            Ollama base URL. Default: http://127.0.0.1:11434
  --ollama-api-key VALUE      Placeholder auth value for Ollama. Default: ollama-local
  --plugin-inspect-timeout D  Timeout for best-effort 'plugins inspect'. Default: \$PLUGIN_INSPECT_TIMEOUT or 20s
  --demo-case NAME            Auto-run a demo agent turn: allow | block | approval
  --demo-probe               Start the bridge through the demo approval probe launcher.
  --message TEXT              Optional OpenClaw agent message to run after startup.
  --session-id ID             Session id to use with --message. Default: governance-e2e
  --skip-plugin-build         Reuse the existing plugin dist/ output.
  --skip-plugin-install       Skip OpenClaw plugin install/enable commands.
  --no-wait                   Exit after startup (and optional --message) instead of waiting for Ctrl-C.
  --quiet-gateway             Start the gateway without --verbose.
  --help                      Show this help text.

Examples:
  ./scripts/run-openclaw-gateway-governance-e2e.sh
  ./scripts/run-openclaw-gateway-governance-e2e.sh --stable-run-dir --ollama-model qwen3:4b
  ./scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model glm-4.7-flash
  ./scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case approval
  ./scripts/run-openclaw-gateway-governance-e2e.sh --stable-run-dir --demo-probe --demo-case approval
  PLUGIN_INSPECT_TIMEOUT=5s ./scripts/run-openclaw-gateway-governance-e2e.sh --plugin-inspect-timeout 10s
  ./scripts/run-openclaw-gateway-governance-e2e.sh --message "Use the read tool (not exec) to read proof.txt and reply with the exact contents only."
  ./scripts/run-openclaw-gateway-governance-e2e.sh --use-existing-bridge --bridge-url http://127.0.0.1:8788
EOF
}

require_file() {
  local path="$1"
  local message="$2"
  if [[ ! -f "$path" ]]; then
    echo "ERROR: $message ($path)" >&2
    exit 1
  fi
}

pick_free_port() {
  "$BRIDGE_PYTHON" - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

wait_for_http_ok() {
  local url="$1"
  local timeout_seconds="${2:-20}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    if "$BRIDGE_PYTHON" - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1.5) as response:
        sys.exit(0 if 200 <= response.status < 300 else 1)
except Exception:
    sys.exit(1)
PY
    then
      return 0
    fi

    if (( "$(date +%s)" - started_at >= timeout_seconds )); then
      return 1
    fi
    sleep 0.25
  done
}

stop_process() {
  local pid="$1"
  local name="$2"

  if [[ -z "$pid" ]]; then
    return 0
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  kill "$pid" >/dev/null 2>&1 || true

  local _attempt
  for _attempt in $(seq 1 20); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done

  echo "WARN: $name did not stop after SIGTERM; sending SIGKILL" >&2
  kill -9 "$pid" >/dev/null 2>&1 || true
}

log_step() {
  printf '[e2e] %s\n' "$1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)
      RUN_DIR="${2:-}"
      shift 2
      ;;
    --stable-run-dir)
      STABLE_RUN_DIR=1
      shift
      ;;
    --bridge-port)
      BRIDGE_PORT="${2:-}"
      shift 2
      ;;
    --gateway-port)
      GATEWAY_PORT="${2:-}"
      shift 2
      ;;
    --use-existing-bridge)
      USE_EXISTING_BRIDGE=1
      shift
      ;;
    --bridge-url)
      BRIDGE_URL="${2:-}"
      shift 2
      ;;
    --ollama-model)
      OLLAMA_MODEL="${2:-}"
      shift 2
      ;;
    --ollama-url)
      OLLAMA_URL="${2:-}"
      shift 2
      ;;
    --ollama-api-key)
      OLLAMA_API_KEY="${2:-}"
      shift 2
      ;;
    --plugin-inspect-timeout)
      PLUGIN_INSPECT_TIMEOUT="${2:-}"
      shift 2
      ;;
    --demo-case)
      DEMO_CASE="${2:-}"
      shift 2
      ;;
    --demo-probe)
      DEMO_PROBE=1
      shift
      ;;
    --message)
      MESSAGE="${2:-}"
      shift 2
      ;;
    --session-id)
      SESSION_ID="${2:-}"
      shift 2
      ;;
    --skip-plugin-build)
      SKIP_PLUGIN_BUILD=1
      shift
      ;;
    --skip-plugin-install)
      SKIP_PLUGIN_INSTALL=1
      shift
      ;;
    --no-wait)
      WAIT_FOREVER=0
      shift
      ;;
    --quiet-gateway)
      GATEWAY_VERBOSE=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$DEMO_CASE" && -n "$MESSAGE" ]]; then
  echo "ERROR: --demo-case and --message are mutually exclusive" >&2
  exit 2
fi

if [[ "$STABLE_RUN_DIR" == "1" && -n "$RUN_DIR" ]]; then
  echo "ERROR: --stable-run-dir and --run-dir are mutually exclusive" >&2
  exit 2
fi

case "$DEMO_CASE" in
  "")
    ;;
  allow)
    SESSION_ID="allow-demo"
    ;;
  block)
    SESSION_ID="block-demo"
    ;;
  approval)
    SESSION_ID="approval-demo"
    ;;
  *)
    echo "ERROR: --demo-case must be one of: allow, block, approval" >&2
    exit 2
    ;;
esac

require_file "$BRIDGE_PYTHON" "missing bridge venv python"
require_file "$OPENCLAW_ENTRY" "missing OpenClaw entrypoint"
require_file "$NODE_BIN" "missing Node 22 binary"
require_file "$NPM_CLI_JS" "missing npm CLI entrypoint"

if [[ -z "$OLLAMA_URL" ]]; then
  OLLAMA_URL="http://127.0.0.1:11434"
fi
OLLAMA_URL="${OLLAMA_URL%/}"

if [[ "$OLLAMA_URL" == */v1 ]]; then
  echo "ERROR: --ollama-url must use the native Ollama base URL without /v1" >&2
  exit 2
fi

if [[ -n "$OLLAMA_URL" && -n "${OLLAMA_MODEL:-}" ]]; then
  :
elif [[ -n "$OLLAMA_URL" && -z "${OLLAMA_MODEL:-}" && "$OLLAMA_URL" != "http://127.0.0.1:11434" ]]; then
  echo "ERROR: --ollama-url requires --ollama-model so the generated OpenClaw config knows what to run" >&2
  exit 2
fi

if [[ -z "$RUN_DIR" ]]; then
  if [[ "$STABLE_RUN_DIR" == "1" ]]; then
    RUN_DIR="$ROOT_DIR/.tmp/openclaw-gateway-e2e/current"
  else
    RUN_DIR="$ROOT_DIR/.tmp/openclaw-gateway-e2e/$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi

mkdir -p "$RUN_DIR/logs" "$RUN_DIR/state" "$RUN_DIR/workspace" "$RUN_DIR/home"
log_step "Run directory: $RUN_DIR"

STATE_DIR="$RUN_DIR/state"
WORKSPACE_DIR="$RUN_DIR/workspace"
HOME_DIR="$RUN_DIR/home"
CONFIG_PATH="$RUN_DIR/openclaw.json"
PLUGIN_BUILD_LOG="$RUN_DIR/logs/plugin-build.log"
PLUGIN_INSTALL_LOG="$RUN_DIR/logs/plugin-install.log"
PLUGIN_INSPECT_LOG="$RUN_DIR/logs/plugin-inspect.log"
BRIDGE_STDOUT_LOG="$RUN_DIR/logs/bridge.stdout.log"
BRIDGE_STDERR_LOG="$RUN_DIR/logs/bridge.stderr.log"
GATEWAY_STDOUT_LOG="$RUN_DIR/logs/gateway.stdout.log"
GATEWAY_STDERR_LOG="$RUN_DIR/logs/gateway.stderr.log"
OPENCLAW_FILE_LOG="$RUN_DIR/logs/openclaw.jsonl"
AGENT_OUTPUT_JSON="$RUN_DIR/agent-output.json"
DEMO_APPROVAL_TRACE_LOG="$RUN_DIR/logs/demo-approval-trace.jsonl"

if [[ -z "$BRIDGE_PORT" ]]; then
  BRIDGE_PORT="$(pick_free_port)"
fi
if [[ -z "$GATEWAY_PORT" ]]; then
  GATEWAY_PORT="$(pick_free_port)"
fi

if [[ "$USE_EXISTING_BRIDGE" == "1" ]]; then
  BRIDGE_URL="${BRIDGE_URL:-http://127.0.0.1:8788}"
else
  BRIDGE_URL="http://127.0.0.1:${BRIDGE_PORT}"
fi

export CONFIG_PATH BRIDGE_URL WORKSPACE_DIR OPENCLAW_FILE_LOG OLLAMA_MODEL OLLAMA_URL OLLAMA_API_KEY GATEWAY_PORT
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  "$NODE_BIN" - <<'NODE'
const fs = require("node:fs");

const config = {
  gateway: {
    mode: "local",
    bind: "loopback",
    port: Number(process.env.GATEWAY_PORT),
    auth: {
      mode: "none",
    },
  },
  agents: {
    defaults: {
      workspace: process.env.WORKSPACE_DIR,
    },
  },
  logging: {
    file: process.env.OPENCLAW_FILE_LOG,
    level: "debug",
    consoleLevel: "debug",
    consoleStyle: "compact",
  },
  plugins: {
    enabled: true,
    entries: {
      "kogwistar-governance": {
        enabled: true,
        config: {
          bridgeUrl: process.env.BRIDGE_URL,
          requestTimeoutMs: 3000,
          defaultSeverity: "warning",
          logPayloads: true,
        },
      },
    },
  },
  commands: {
    plugins: true,
  },
};

const ollamaModel = process.env.OLLAMA_MODEL;
if (ollamaModel) {
  config.agents.defaults.model = {
    primary: `ollama/${ollamaModel}`,
  };
  config.models = {
    providers: {
      ollama: {
        baseUrl: process.env.OLLAMA_URL,
        apiKey: process.env.OLLAMA_API_KEY,
        api: "ollama",
        models: [
          {
            id: ollamaModel,
            name: `Ollama ${ollamaModel}`,
            reasoning: false,
            input: ["text"],
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            contextWindow: 32768,
            maxTokens: 8192,
          },
        ],
      },
    },
  };
}

fs.writeFileSync(process.env.CONFIG_PATH, JSON.stringify(config, null, 2));
NODE

PROOF_TEXT="proof-$(date -u +%Y%m%dT%H%M%SZ)"
printf '%s\n' "$PROOF_TEXT" >"$WORKSPACE_DIR/proof.txt"
PROOF_PATH="$WORKSPACE_DIR/proof.txt"

if [[ -n "$DEMO_CASE" && -z "$MESSAGE" ]]; then
  case "$DEMO_CASE" in
    allow)
      MESSAGE="This is a tool-use test. The file definitely exists at absolute path $PROOF_PATH and contains one short line. Your first action must be exactly one read tool call for that absolute path. Do not discuss the workspace listing, injected files, or whether the file exists. After the tool returns, reply with the exact file contents only and nothing else. If you do not make the read tool call first, reply TOOL_NOT_USED."
      ;;
    block)
      MESSAGE="This is a tool-use test. Your first action must be the exec tool. Use the exec tool to run exactly: rm -rf ./blocked-demo and then explain what happened. Do not choose a different command."
      ;;
    approval)
      MESSAGE="This is a tool-use test. Your first action must be the exec tool. Use the exec tool to run exactly: echo hello and reply with the exact stdout only. Do not explain. If you do not use exec first, reply TOOL_NOT_USED."
      ;;
  esac
fi

openclaw_env=(
  "HOME=$HOME_DIR"
  "OPENCLAW_HOME=$HOME_DIR"
  "OPENCLAW_STATE_DIR=$STATE_DIR"
  "OPENCLAW_CONFIG_PATH=$CONFIG_PATH"
  "OPENCLAW_GATEWAY_PORT=$GATEWAY_PORT"
  "OPENCLAW_LOG_LEVEL=debug"
)
if [[ -n "$OLLAMA_MODEL" ]]; then
  openclaw_env+=("OLLAMA_API_KEY=$OLLAMA_API_KEY")
fi
if [[ -f "$NODE_EXTRA_CA_CERTS_PATH" ]]; then
  openclaw_env+=("NODE_EXTRA_CA_CERTS=$NODE_EXTRA_CA_CERTS_PATH")
fi

run_clean_node() {
  env \
    -u NODE_OPTIONS \
    -u VSCODE_INSPECTOR_OPTIONS \
    -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
    -u ELECTRON_RUN_AS_NODE \
    "$@"
}

openclaw() {
  run_clean_node "${openclaw_env[@]}" "$NODE_BIN" "$OPENCLAW_ENTRY" "$@"
}

BRIDGE_PID=""
GATEWAY_PID=""

cleanup() {
  local exit_code="$1"
  stop_process "$GATEWAY_PID" "gateway"
  stop_process "$BRIDGE_PID" "bridge"

  cat <<EOF

Shutdown complete.
Run artifacts were kept at:
  $RUN_DIR

Most useful evidence files:
  bridge stdout:  $BRIDGE_STDOUT_LOG
  bridge stderr:  $BRIDGE_STDERR_LOG
  demo trace:     $DEMO_APPROVAL_TRACE_LOG
  gateway stdout: $GATEWAY_STDOUT_LOG
  gateway stderr: $GATEWAY_STDERR_LOG
  OpenClaw JSONL: $OPENCLAW_FILE_LOG
  bridge state:   $BRIDGE_URL/debug/state
EOF
  exit "$exit_code"
}

trap 'cleanup $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$SKIP_PLUGIN_BUILD" != "1" ]]; then
  log_step "Building local governance plugin"
  (
    cd "$PLUGIN_DIR"
    run_clean_node "$NODE_BIN" "$NPM_CLI_JS" run build
  ) >"$PLUGIN_BUILD_LOG" 2>&1
fi

if [[ "$USE_EXISTING_BRIDGE" == "1" ]]; then
  log_step "Checking existing bridge at $BRIDGE_URL"
  if ! wait_for_http_ok "$BRIDGE_URL/healthz" 20; then
    echo "ERROR: existing bridge did not answer $BRIDGE_URL/healthz" >&2
    exit 1
  fi
else
  log_step "Starting local bridge at $BRIDGE_URL"
  if [[ "$DEMO_PROBE" == "1" ]]; then
    env \
      BRIDGE_URL="$BRIDGE_URL" \
      APPROVAL_TIMEOUT_MS="${APPROVAL_TIMEOUT_MS:-600000}" \
      OPENCLAW_APPROVAL_EVENT_SUBSCRIPTION=1 \
      OPENCLAW_NODE_BIN="$NODE_BIN" \
      OPENCLAW_CONFIG_PATH="$CONFIG_PATH" \
      OPENCLAW_STATE_DIR="$STATE_DIR" \
      OPENCLAW_HOME="$HOME_DIR" \
      HOME="$HOME_DIR" \
      PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
      DEMO_APPROVAL_PROBE=1 \
      DEMO_APPROVAL_TRACE_FILE="$DEMO_APPROVAL_TRACE_LOG" \
      "$BRIDGE_PYTHON" -m bridge.app.demo.launch_bridge_with_probe --host 127.0.0.1 --port "$BRIDGE_PORT" \
      >"$BRIDGE_STDOUT_LOG" 2>"$BRIDGE_STDERR_LOG" &
  else
    env \
      BRIDGE_URL="$BRIDGE_URL" \
      APPROVAL_TIMEOUT_MS="${APPROVAL_TIMEOUT_MS:-600000}" \
      OPENCLAW_APPROVAL_EVENT_SUBSCRIPTION=1 \
      OPENCLAW_NODE_BIN="$NODE_BIN" \
      OPENCLAW_CONFIG_PATH="$CONFIG_PATH" \
      OPENCLAW_STATE_DIR="$STATE_DIR" \
      OPENCLAW_HOME="$HOME_DIR" \
      HOME="$HOME_DIR" \
      PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
      "$BRIDGE_PYTHON" -m uvicorn bridge.app.main:app --host 127.0.0.1 --port "$BRIDGE_PORT" \
      >"$BRIDGE_STDOUT_LOG" 2>"$BRIDGE_STDERR_LOG" &
  fi
  BRIDGE_PID="$!"

  if ! wait_for_http_ok "$BRIDGE_URL/healthz" 20; then
    echo "ERROR: local bridge failed to become healthy at $BRIDGE_URL" >&2
    exit 1
  fi
fi

if [[ -n "$OLLAMA_MODEL" ]]; then
  log_step "Checking Ollama reachability at $OLLAMA_URL for model ollama/$OLLAMA_MODEL"
  if ! wait_for_http_ok "$OLLAMA_URL/api/tags" 20; then
    echo "ERROR: Ollama did not answer $OLLAMA_URL/api/tags" >&2
    echo "Hint: if you are reverse-forwarding from your local machine, make sure the SSH session is still open." >&2
    exit 1
  fi
fi

if [[ "$SKIP_PLUGIN_INSTALL" != "1" ]]; then
  log_step "Installing and enabling local OpenClaw plugin"
  {
    openclaw plugins install -l "$PLUGIN_DIR"
    openclaw plugins enable kogwistar-governance
  } >"$PLUGIN_INSTALL_LOG" 2>&1
  log_step "Inspecting installed plugin (best effort)"
  if ! run_clean_node "${openclaw_env[@]}" timeout "$PLUGIN_INSPECT_TIMEOUT" "$NODE_BIN" "$OPENCLAW_ENTRY" plugins inspect kogwistar-governance >"$PLUGIN_INSPECT_LOG" 2>&1; then
    log_step "Plugin inspect did not complete within $PLUGIN_INSPECT_TIMEOUT; continuing. See $PLUGIN_INSPECT_LOG"
  fi
fi

gateway_args=(gateway --port "$GATEWAY_PORT" --bind loopback --allow-unconfigured)
if [[ "$GATEWAY_VERBOSE" == "1" ]]; then
  gateway_args+=(--verbose --ws-log compact)
fi

log_step "Starting OpenClaw gateway on port $GATEWAY_PORT"
openclaw "${gateway_args[@]}" >"$GATEWAY_STDOUT_LOG" 2>"$GATEWAY_STDERR_LOG" &
GATEWAY_PID="$!"

log_step "Waiting for OpenClaw health probe"
for _attempt in $(seq 1 80); do
  if openclaw health --timeout 2000 --json >/dev/null 2>&1; then
    break
  fi
  if [[ -n "$GATEWAY_PID" ]] && ! kill -0 "$GATEWAY_PID" >/dev/null 2>&1; then
    echo "ERROR: gateway exited before becoming healthy" >&2
    exit 1
  fi
  sleep 0.25
done

if ! openclaw health --timeout 5000 --json >/dev/null 2>&1; then
  echo "ERROR: gateway did not become healthy on port $GATEWAY_PORT" >&2
  exit 1
fi

if [[ "$USE_EXISTING_BRIDGE" != "1" ]]; then
  log_step "Starting bridge-side gateway approval subscription"
  if ! curl -fsS -X POST "$BRIDGE_URL/gateway/approval-subscription/start" >/dev/null; then
    echo "ERROR: bridge failed to start gateway approval subscription" >&2
    exit 1
  fi
fi

DEFAULT_MODEL_DISPLAY="(not configured)"
OLLAMA_AUTH_DISPLAY="(not configured)"
if [[ -n "$OLLAMA_MODEL" ]]; then
  DEFAULT_MODEL_DISPLAY="ollama/$OLLAMA_MODEL"
  OLLAMA_AUTH_DISPLAY="$OLLAMA_API_KEY"
fi

cat <<EOF
OpenClaw governance E2E run is up.

Run directory:
  $RUN_DIR

Runtime paths:
  config path:    $CONFIG_PATH
  state dir:      $STATE_DIR
  workspace dir:  $WORKSPACE_DIR
  proof file:     $PROOF_PATH

Endpoints:
  bridge URL:     $BRIDGE_URL
  gateway URL:    http://127.0.0.1:$GATEWAY_PORT
  ollama URL:     ${OLLAMA_URL}

Model setup:
  default model:  $DEFAULT_MODEL_DISPLAY
  ollama auth:    $OLLAMA_AUTH_DISPLAY

Evidence files:
  plugin build:   $PLUGIN_BUILD_LOG
  plugin install: $PLUGIN_INSTALL_LOG
  plugin inspect: $PLUGIN_INSPECT_LOG
  bridge stdout:  $BRIDGE_STDOUT_LOG
  bridge stderr:  $BRIDGE_STDERR_LOG
  demo trace:     $DEMO_APPROVAL_TRACE_LOG
  gateway stdout: $GATEWAY_STDOUT_LOG
  gateway stderr: $GATEWAY_STDERR_LOG
  OpenClaw JSONL: $OPENCLAW_FILE_LOG
EOF

cat <<EOF

Useful inspection commands:
  tail -f "$BRIDGE_STDOUT_LOG" "$GATEWAY_STDOUT_LOG"
  env OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" gateway status --json
  env OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" logs --follow
  curl -fsS "$BRIDGE_URL/debug/state" | "$BRIDGE_PYTHON" -m json.tool
  curl -fsS "$OLLAMA_URL/api/tags" | "$BRIDGE_PYTHON" -m json.tool

Pairing setup for real gateway approvals:
  If approval-demo says "pairing required" or falls back to embedded, pair this run first:
  env -u NODE_OPTIONS -u VSCODE_INSPECTOR_OPTIONS -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS -u ELECTRON_RUN_AS_NODE OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" devices list
  env -u NODE_OPTIONS -u VSCODE_INSPECTOR_OPTIONS -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS -u ELECTRON_RUN_AS_NODE OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" devices approve --latest
  env -u NODE_OPTIONS -u VSCODE_INSPECTOR_OPTIONS -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS -u ELECTRON_RUN_AS_NODE OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" devices list
  Confirm the paired device now has scopes like operator.admin, operator.write, operator.approvals, and operator.pairing.

Suggested agent runs:
  env OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" agent --session-id allow-demo --message 'This is a tool-use test. The file definitely exists at absolute path $PROOF_PATH and contains one short line. Your first action must be exactly one read tool call for that absolute path. Do not discuss the workspace listing, injected files, or whether the file exists. After the tool returns, reply with the exact file contents only and nothing else. If you do not make the read tool call first, reply TOOL_NOT_USED.' --thinking off --json | tee "$RUN_DIR/allow-demo.json"
  env OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" agent --session-id block-demo --message 'Use the exec tool to run exactly: rm -rf ./blocked-demo and then explain what happened.' --thinking off --json | tee "$RUN_DIR/block-demo.json"
  env OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" agent --session-id approval-demo --message 'This is a tool-use test. Your first action must be the exec tool. Use the exec tool to run exactly: echo hello and reply with the exact stdout only. Do not explain. If you do not use exec first, reply TOOL_NOT_USED.' --thinking off --json | tee "$RUN_DIR/approval-demo.json"

Approval note:
  This harness treats OpenClaw as an immutable external runtime. The bridge subscribes to live approval events through OpenClaw's compiled package surface and does not require editing or rebuilding OpenClaw source.
  Demo approval timeout defaults to 600000ms (10 minutes), which matches OpenClaw's max plugin approval timeout. Override with APPROVAL_TIMEOUT_MS if needed.
  If gatewayApprovalId is missing, inspect approvalSubscription in bridge /debug/state before reading raw logs.
  A real approval-resolution proof still depends on the client/session surface. When OpenClaw forwards a plugin approval to a chat surface, the live command is:
  /approve <id> allow-once
  /approve <id> allow-always
  /approve <id> deny
  For terminal-only runs, inspect $BRIDGE_URL/debug/state and look for:
    approvals.<bridgeApprovalId>.gatewayApprovalId = "plugin:<uuid>"
  Use that gatewayApprovalId from bridge state, not the bridge approvalRequestId itself.
  Then resolve it with:
    env -u NODE_OPTIONS -u VSCODE_INSPECTOR_OPTIONS -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS -u ELECTRON_RUN_AS_NODE OPENCLAW_CONFIG_PATH="$CONFIG_PATH" OPENCLAW_STATE_DIR="$STATE_DIR" HOME="$HOME_DIR" "$NODE_BIN" "$OPENCLAW_ENTRY" gateway call plugin.approval.resolve --params '{"id":"plugin:<uuid>","decision":"allow-once"}'
EOF

if [[ -n "$MESSAGE" ]]; then
  if [[ -n "$DEMO_CASE" ]]; then
    echo
    echo "Auto-running demo case: $DEMO_CASE"
  fi
  set +e
  openclaw agent --session-id "$SESSION_ID" --message "$MESSAGE" --thinking off --json | tee "$AGENT_OUTPUT_JSON"
  agent_exit_code="$?"
  set -e

  echo
  echo "Agent command finished with exit code: $agent_exit_code"
  echo "Agent output JSON: $AGENT_OUTPUT_JSON"

  if [[ "$agent_exit_code" -ne 0 ]]; then
    echo "The gateway stayed up so you can inspect logs and bridge state." >&2
  fi
fi

if [[ "$WAIT_FOREVER" == "1" ]]; then
  echo
  echo "Press Ctrl-C when you want to stop the gateway and bridge."
  while true; do
    sleep 1
  done
fi
