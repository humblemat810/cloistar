# OpenClaw Governance E2E Quickstart

This is the fastest path in this repo to stand up a real local bridge plus a repo-local OpenClaw gateway, then inspect whether governance is actually firing.

The happy path below assumes:

- this repo is checked out on a remote machine
- your own Ollama is running on your local machine
- you want to reverse-forward your local Ollama port to the remote machine

## What This Helper Does

Use [run-openclaw-gateway-governance-e2e.sh](/home/azureuser/cloistar/scripts/run-openclaw-gateway-governance-e2e.sh) when you want one command that:

- builds the local plugin
- starts the FastAPI bridge from this repo
- creates an isolated OpenClaw config/state/workspace
- installs and enables the local governance plugin in that isolated OpenClaw state
- starts the repo-local OpenClaw gateway
- prints the exact config path, log paths, and bridge debug URL to inspect
- shuts down cleanly on `Ctrl-C` while keeping all artifacts on disk

## 1. Reverse-Forward Your Local Ollama Port

Run this on your local machine, not on the remote machine.

If your local Ollama uses the normal port `11434`:

```bash
ssh -R 11434:127.0.0.1:11434 user@<remote-host>
```


Keep that SSH session open while you run the E2E helper.

## 2. Verify Ollama From The Remote Machine

On the remote machine:

```bash
curl http://127.0.0.1:11434/api/tags
```

If this fails, the OpenClaw helper will fail too.

Important: use the native Ollama API base URL, not `/v1`. OpenClaw’s own Ollama docs call that out in [ollama.md](openclaw/docs/providers/ollama.md#L11).

## 3. Start The Full Governance E2E Stack

From the repo root on the remote machine:

```bash
cd ~/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model <your-model>
```

Example:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model glm-4.7-flash
```

If you want the helper to immediately run a governance demo turn after startup:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --ollama-model qwen3:4b \
  --demo-case approval
```

This is the fastest way to see the stack do real work. The helper will:

- start the bridge
- start the OpenClaw gateway
- auto-run one agent turn
- print the agent output in your terminal
- keep the bridge and gateway alive so you can inspect logs and bridge state

### Recommended For Pairing And Approval Work

When you are testing `requireApproval`, use a stable reusable run directory so pairing and local OpenClaw state do not reset every run:

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --stable-run-dir \
  --ollama-model qwen3:4b
```

This uses:

```bash
/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current
```

as the persistent run directory unless you override it with `--run-dir`.

Fast path for `requireApproval` with persistent state:

1. Start the helper with `--stable-run-dir`.
2. In a second terminal set:

```bash
RUN_DIR="/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current"
```

3. Check for pending device pairing requests:

```bash
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  devices list
```

4. If you see a pending request, approve it:

```bash
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  devices approve --latest
```

5. Re-run `devices list` and confirm the paired device now has broader scopes like:

- `operator.admin`
- `operator.write`
- `operator.approvals`
- `operator.pairing`

6. Only after that, run the real approval demo and resolve the Gateway approval id.

Design rule for this harness:

- OpenClaw is treated as an external immutable compiled runtime.
- Always integrate through standard Gateway subscriptions, operator APIs, and compiled package entrypoints.
- Never rely on patching `openclaw/src` just to expose approval ids or make this workflow operate.
- If the bridge needs more approval visibility, the correct fix is to subscribe to Gateway approval events and record them on the bridge side.

Approval timeout for demos:

- The bridge now defaults demo approvals to `600000` ms (10 minutes).
- That matches OpenClaw's documented maximum plugin approval timeout.
- You can override it by exporting `APPROVAL_TIMEOUT_MS` before starting the helper, but values above `600000` will still be capped by OpenClaw.
- If `gatewayApprovalId` is missing, inspect `approvalSubscription` in bridge `/debug/state` first. That is the bridge-side truth for whether the Gateway approval listener started, connected, and saw any approval events.

If you want the helper to use a different Ollama base URL:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --ollama-model <your-model> \
  --ollama-url http://127.0.0.1:11434
```

The helper prints:

- the run directory
- the generated OpenClaw config path
- the isolated state directory
- the workspace and proof file paths
- bridge stdout/stderr logs
- gateway stdout/stderr logs
- OpenClaw JSONL log file
- the bridge debug-state URL

## Using Gemini Instead Of Ollama

The script is currently Ollama-first, but Gemini works fine for real agent turns as long as the key is present in the parent shell before you launch the helper.

OpenClaw’s Gemini provider docs are in [google.md](/home/azureuser/cloistar/openclaw/docs/providers/google.md#L16).

1. Export a Gemini key on the remote machine before starting the helper:

```bash
export GEMINI_API_KEY='...'
```

2. Start the helper normally:

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh
```

3. After the helper prints the isolated config/state paths, point that isolated OpenClaw instance at a Gemini model:

```bash
env OPENCLAW_CONFIG_PATH="<printed-config-path>" \
    OPENCLAW_STATE_DIR="<printed-state-dir>" \
    HOME="<printed-home-dir>" \
    /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
    /home/azureuser/cloistar/openclaw/openclaw.mjs \
    models set google/gemini-3.1-pro-preview
```

4. Run the same `agent` commands the helper prints.

Notes:

- You can also use `GOOGLE_API_KEY`.
- If the gateway was already running when you changed the model, OpenClaw should reload from config, but if it looks stale, restart the helper.

## Using Azure OpenAI Instead Of Ollama

Azure OpenAI needs more than just an API key. You also need the Azure base URL and an explicit provider entry in the generated OpenClaw config.

OpenClaw’s related provider docs are in [openai.md](/home/azureuser/cloistar/openclaw/docs/providers/openai.md#L257).

1. Export the key on the remote machine before starting the helper:

```bash
export AZURE_OPENAI_API_KEY='...'
```

2. Start the helper once so it prints the isolated config path:

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh
```

3. Edit the printed `openclaw.json` and add an Azure provider entry like this:

```json
{
  "models": {
    "providers": {
      "azure-openai-responses": {
        "baseUrl": "https://<your-resource>.openai.azure.com/openai/v1",
        "apiKey": "${AZURE_OPENAI_API_KEY}",
        "api": "azure-openai-responses",
        "models": [
          {
            "id": "gpt-5.4",
            "name": "Azure GPT-5.4",
            "input": ["text", "image"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 128000,
            "maxTokens": 32000
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "azure-openai-responses/gpt-5.4"
      }
    }
  }
}
```

4. Restart the helper, or if you kept it running, run:

```bash
env OPENCLAW_CONFIG_PATH="<printed-config-path>" \
    OPENCLAW_STATE_DIR="<printed-state-dir>" \
    HOME="<printed-home-dir>" \
    /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
    /home/azureuser/cloistar/openclaw/openclaw.mjs \
    gateway restart
```

Notes:

- Replace the base URL with your real Azure resource URL.
- Replace `gpt-5.4` with the Azure model/deployment you actually use.
- Azure is not yet first-class in the helper script. If you want, the next step is to add `--azure-openai-url` and `--azure-openai-model` flags so the helper writes this section for you automatically.

## 4. Run A Real Agent Turn

The helper prints ready-to-copy commands for three useful scenarios:

- `allow`: safe `read` call
- `block`: dangerous `exec`
- `approval`: `exec` that should require approval

You can also ask the helper to run one of those automatically:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case allow
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case block
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case approval
```

The built-in demo prompts are intentionally strict:

- `allow`: use exactly one `read` tool call on the absolute `proof.txt` path and return the exact contents only
- `block`: run exactly `rm -rf ./blocked-demo`
- `approval`: run exactly `echo hello` and return the exact stdout only

If the model ignores the requested tool, the `allow` and `approval` prompts instruct it to reply `TOOL_NOT_USED`, which makes tool-skipping obvious in the terminal output.

The `allow` prompt is extra strict on purpose for small local models:

- it names the exact absolute file path
- it says the file definitely exists
- it says the first action must be a `read` tool call
- it tells the model not to argue about the injected workspace file list

This is meant to make even weaker local models more likely to actually call `read`, so the governance path can be demonstrated without depending on a frontier model.

### Recommended Demo Order

Run these in order so it is easy to understand what changed between scenarios:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case allow
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case block
bash scripts/run-openclaw-gateway-governance-e2e.sh --ollama-model qwen3:4b --demo-case approval
```

What each case is meant to prove:

- `allow`
  - OpenClaw should choose the built-in `read` tool.
  - The plugin should send `before_tool_call` and `after_tool_call` to the bridge.
  - The bridge should return `allow`.
  - Bridge state should show observed, decision recorded, and completed events.

- `block`
  - OpenClaw should attempt to use the built-in `exec` tool.
  - The bridge policy should match `rm -rf` and return `block`.
  - Bridge state should show observed and decision recorded, without completion.

- `approval`
  - OpenClaw should attempt to use the built-in `exec` tool.
  - The bridge policy should return `requireApproval`.
  - Bridge state should show observed, decision recorded, approval requested, and execution suspended.
  - This proves approval was triggered even if no chat/UI prompt is visible in the launcher terminal.

The simplest first proof run is:

```bash
env OPENCLAW_CONFIG_PATH="<printed-config-path>" \
    OPENCLAW_STATE_DIR="<printed-state-dir>" \
    HOME="<printed-home-dir>" \
    /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
    /home/azureuser/cloistar/openclaw/openclaw.mjs \
    agent \
    --session-id allow-demo \
    --message 'Use the read tool (not exec) to read proof.txt and reply with the exact contents only.' \
    --thinking off \
    --json
```

You can also have the helper run a first turn automatically:

```bash
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --ollama-model <your-model> \
  --demo-case allow
```

## 5. Inspect The Evidence

Watch both sides:

```bash
tail -f <bridge-stdout-log> <gateway-stdout-log>
```

For the latest run directory, this is a practical live-tail command:

```bash
RUN_DIR="$(ls -td /home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/* | head -n 1)"
tail -f \
  "$RUN_DIR/logs/bridge.stdout.log" \
  "$RUN_DIR/logs/gateway.stdout.log" \
  "$RUN_DIR/logs/gateway.stderr.log"
```

Inspect the bridge state:

```bash
curl -fsS <printed-bridge-url>/debug/state | /home/azureuser/cloistar/.venv/bin/python -m json.tool
```

Follow OpenClaw’s own log stream:

```bash
env OPENCLAW_CONFIG_PATH="<printed-config-path>" \
    OPENCLAW_STATE_DIR="<printed-state-dir>" \
    HOME="<printed-home-dir>" \
    /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
    /home/azureuser/cloistar/openclaw/openclaw.mjs \
    logs --follow
```

What you want to see:

- plugin install succeeded in `plugin-install.log`
- gateway started and stayed healthy
- bridge received `before_tool_call` and `after_tool_call`
- bridge state shows observed, decision, and completion events
- for approval cases, bridge state shows approval request and approval resolution

### How To Interpret The Demo Output

- If the helper reaches `OpenClaw governance E2E run is up.`, startup succeeded.
- If the auto-run demo prints a normal model answer but bridge state stays empty, the model probably did not use a tool.
- If the auto-run demo prints `TOOL_NOT_USED`, the prompt was followed but tool use did not happen.
- If bridge state shows `approval_requested` and `execution_suspended`, the governance layer did trigger approval successfully.
- The launcher terminal itself is not an approval UI. Approval resolution still depends on the OpenClaw client or chat surface connected to that session.

### Most Useful Files During A Demo Run

- `plugin-install.log`
  - proves the local plugin installed and enabled in the isolated OpenClaw state
- `bridge.stdout.log`
  - shows bridge requests such as `/policy/before-tool-call` and `/events/after-tool-call`
- `gateway.stdout.log`
  - shows OpenClaw gateway runtime activity
- `gateway.stderr.log`
  - useful when the gateway is up but behaves oddly
- `openclaw.jsonl`
  - OpenClaw structured runtime log written for the isolated run

## 6. Approval Resolution

The helper gets you to a real gateway run, but a true approval-resolution proof still depends on the client/session surface that receives the approval prompt.

When OpenClaw forwards a plugin approval to a chat-capable surface, the relevant live commands are:

```text
/approve <id> allow-once
/approve <id> allow-always
/approve <id> deny
```

## 7. Real `requireApproval` Walkthrough

Use this when you want more than a suspended approval. The goal here is to get as far as possible toward a real resolved `requireApproval` run.

### What this requires

There are two separate layers involved:

- the bridge policy must return `requireApproval`
- the OpenClaw Gateway must have an approved device/client identity so `openclaw agent` can use the Gateway path instead of falling back to embedded mode

If the Gateway client is not paired, you will see:

```text
gateway connect failed: GatewayClientRequestError: pairing required
Gateway agent failed; falling back to embedded
```

That pairing requirement is OpenClaw's own device/client trust gate, not the Kogwistar bridge policy.

### Step 1. Start the stack without auto-running a demo

```bash
cd /home/azureuser/cloistar
bash scripts/run-openclaw-gateway-governance-e2e.sh --stable-run-dir --ollama-model 'qwen3:4b'
```

Keep that terminal open.

### Step 2. Reuse the same isolated OpenClaw run

In a second terminal, set `RUN_DIR` to the helper's printed run directory:

```bash
RUN_DIR="/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current"
```

If you did not use `--stable-run-dir`, use the helper's printed timestamped run directory instead.

Every OpenClaw command below must reuse that same isolated environment:

```bash
env \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  <subcommand>
```

Do not mix these commands with your default `~/.openclaw` state.

### Why `--stable-run-dir` helps

- device pairing stays in the same isolated OpenClaw state across restarts
- approval debugging is easier because the config/state/home paths do not keep changing
- `gateway call` commands are less error-prone because `RUN_DIR` is stable
- you can still inspect older timestamped runs when you want a fresh isolated experiment

### Step 3. Check pending Gateway device pairing requests

```bash
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  devices list
```

If you see a pending request, approve it:

```bash
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  devices approve --latest
```

If needed, re-run `devices list` to confirm the client is now paired.

What you want to see after approval:

- no pending request for that device
- the paired device now has scopes including:
  - `operator.admin`
  - `operator.write`
  - `operator.approvals`
  - `operator.pairing`

### Step 4. Trigger the approval case

```bash
env \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  agent \
  --session-id approval-demo \
  --message 'This is a tool-use test. Your first action must be the exec tool. Use the exec tool to run exactly: echo hello and reply with the exact stdout only. Do not explain. If you do not use exec first, reply TOOL_NOT_USED.' \
  --thinking off \
  --json
```

What you want to see:

- no `Gateway agent failed; falling back to embedded`
- plugin `before_tool_call` for `exec`
- bridge state showing `require_approval`

### Step 5. Inspect the bridge state

Use the bridge URL printed by the helper:

```bash
curl -fsS <printed-bridge-url>/debug/state | /home/azureuser/cloistar/.venv/bin/python -m json.tool
```

For a real `requireApproval` case, you want to see:

- `governance.tool_call_observed.v1`
- `governance.decision_recorded.v1` with `disposition: "require_approval"`
- `governance.approval_requested.v1`
- `governance.execution_suspended.v1`

### Step 6. Resolve the approval

This part still needs an OpenClaw approval surface.

OpenClaw can forward approval prompts to operator surfaces and resolve them with:

```text
/approve <id> allow-once
/approve <id> allow-always
/approve <id> deny
```

For a terminal-only workflow, you can also resolve the pending plugin approval directly through the OpenClaw Gateway RPC:

```bash
env \
  -u NODE_OPTIONS \
  -u VSCODE_INSPECTOR_OPTIONS \
  -u VSCODE_DEBUGPY_ADAPTER_ENDPOINTS \
  -u ELECTRON_RUN_AS_NODE \
  OPENCLAW_CONFIG_PATH="$RUN_DIR/openclaw.json" \
  OPENCLAW_STATE_DIR="$RUN_DIR/state" \
  HOME="$RUN_DIR/home" \
  /home/azureuser/.nvm/versions/node/v22.22.2/bin/node \
  /home/azureuser/cloistar/openclaw/openclaw.mjs \
  gateway call plugin.approval.resolve \
  --params '{"id":"plugin:<uuid>","decision":"allow-once"}'
```

Allowed decisions:

- `allow-once`
- `allow-always`
- `deny`

Immutable OpenClaw boundary:

- Treat OpenClaw as an external compiled runtime for this harness.
- The bridge subscribes to Gateway approval events through OpenClaw's compiled package entrypoints under `openclaw/dist`.
- Do not patch `openclaw/src` or rely on source-only edits for this workflow.

Notes:

- This resolves the approval through OpenClaw itself, not by writing directly to the bridge.
- Do not use the bridge `/debug/state` approval ids here. `plugin.approval.resolve` expects the OpenClaw Gateway approval id, not the bridge approval request id.
- Recover the correct OpenClaw id from the bridge state, not from OpenClaw source logs. After the bridge-side approval listener sees the Gateway event, `/debug/state` includes:

```json
{
  "approvals": {
    "<bridge-approval-id>": {
      "gatewayApprovalId": "plugin:<uuid>"
    }
  }
}
```

- If the model/runtime created duplicate pending approvals, resolve each pending `gatewayApprovalId` you see in `/debug/state`.
- After resolution, check `/debug/state` again for:
  - `governance.approval_resolved.v1`
  - `governance.execution_resumed.v1` or `governance.execution_denied.v1`
  - `governance.tool_call_completed.v1`

If no approval surface is connected, the request can be cancelled or time out, and the bridge will record a negative resolution such as:

- `cancelled`
- `timeout`
- `deny`

### Current practical boundary in this repo

Today we have already proven:

- `allow` end to end
- `block` end to end
- `requireApproval` up to suspension and bridge-side approval recording

What is still only partially proven live is a positive human approval resolution flowing back through a paired OpenClaw approval surface.

That behavior is described in OpenClaw’s docs and source:

- [hooks.md](/home/azureuser/cloistar/openclaw/docs/automation/hooks.md#L499)
- [exec-approvals.md](/home/azureuser/cloistar/openclaw/docs/tools/exec-approvals.md#L368)

## Three-Terminal Harness Cases

The subprocess harness in [run-openclaw-governance-three-terminal.py](/home/azureuser/cloistar/scripts/run-openclaw-governance-three-terminal.py) now documents and supports these cases:

Two live E2E styles now exist:

- self-starting
  - The harness starts the helper itself, which in turn starts bridge + gateway + isolated OpenClaw state.
  - This is the simplest fully self-contained live test path.
  - By default the harness uses `--stable-run-dir`, so it reuses the standard persistent run directory at:

```bash
/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current
```

  - If you want an isolated disposable run directory instead, pass `--no-stable-run-dir --run-dir <path>`.
- attached-stack
  - The harness assumes the helper is already running and attaches only the agent + approver subprocesses to that existing stack.
  - This is useful when you want to keep one stable run directory alive and run multiple live cases against it.
  - In attached-stack mode, `--run-dir` must point at the already existing isolated OpenClaw state that matches the running bridge/gateway.
  - If you omit `--run-dir`, the harness defaults to the same standard run directory:

```bash
/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current
```

  - That default is only correct if your existing helper was started against that same run directory.

- `allow`
  - Uses a read-tool prompt against the generated proof file.
  - Expected behavior: no approval flow; tool completes and returns the proof text.
- `block`
  - Uses a destructive exec prompt such as `rm -rf ./blocked-demo`.
  - Expected behavior: policy blocks before any approval request is created.
- `approval`
  - Uses `exec echo hello`.
  - Expected behavior: bridge policy creates `requireApproval`, then the approval surface decides what happens next.

For the `approval` case, the harness supports these approval modes:

- `auto-allow`
  - Auto-resolve bridge plugin approvals and downstream OpenClaw exec approvals with `allow-once`.
- `auto-deny`
  - Auto-resolve bridge plugin approvals and downstream OpenClaw exec approvals with `deny`.
- `manual`
  - Prompt on the console for each approval decision.
- `llm`
  - Use a second OpenClaw agent call as a simple approval judge that returns `ALLOW_ONCE` or `DENY`.

Examples:

```bash
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --demo-case allow
```

```bash
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --demo-case block
```

```bash
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --demo-case approval \
  --approval-mode auto-allow
```

```bash
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --demo-case approval \
  --approval-mode manual
```

```bash
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --demo-case approval \
  --approval-mode llm
```

Attached-stack example:

```bash
RUN_DIR="/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current"
/home/azureuser/cloistar/.venv/bin/python \
  scripts/run-openclaw-governance-three-terminal.py \
  --use-existing-stack \
  --bridge-url http://127.0.0.1:<bridge-port> \
  --run-dir "$RUN_DIR" \
  --demo-case approval \
  --approval-mode auto-allow
```

Run directory rule of thumb:

- self-starting harness with no extra flags:
  - automatically uses the default stable run directory
- self-starting harness with `--no-stable-run-dir --run-dir ...`:
  - creates/uses that explicit disposable run directory
- attached-stack harness:
  - must attach to the same run directory the already running helper/OpenClaw stack is using

The matching pytest coverage is now split the same way:

- self-starting live E2E:
  - [test_openclaw_three_terminal_e2e.py](/home/azureuser/cloistar/bridge/tests/test_openclaw_three_terminal_e2e.py)
- attached-stack live E2E:
  - [test_openclaw_three_terminal_existing_stack_e2e.py](/home/azureuser/cloistar/bridge/tests/test_openclaw_three_terminal_existing_stack_e2e.py)

Quick run commands:

- Fast in-process integration matrix:

```bash
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_policy_matrix_pytest.py -q
```

- Self-starting live E2E:

```bash
OPENCLAW_RUN_E2E=1 \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_e2e.py -q
```

- Self-starting live E2E with manual approval case enabled:

```bash
OPENCLAW_RUN_E2E=1 OPENCLAW_RUN_MANUAL_E2E=1 \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_e2e.py -q
```

- Attached-stack live E2E:

```bash
OPENCLAW_RUN_E2E=1 \
OPENCLAW_RUN_EXISTING_STACK_E2E=1 \
OPENCLAW_EXISTING_BRIDGE_URL=http://127.0.0.1:<bridge-port> \
OPENCLAW_EXISTING_RUN_DIR=/home/azureuser/cloistar/.tmp/openclaw-gateway-e2e/current \
/home/azureuser/cloistar/.venv/bin/python -m pytest \
  bridge/tests/test_openclaw_three_terminal_existing_stack_e2e.py -q
```

## Common Gotchas

- If `curl http://127.0.0.1:11434/api/tags` fails on the remote machine, the SSH reverse tunnel is not working.
- Do not use an Ollama URL ending in `/v1`.
- Keep the SSH tunnel session open for the whole run.
- If the agent run fails but the gateway stays up, inspect the printed log files before changing code.
- If you are testing pairing or approval resolution, prefer `--stable-run-dir` so the trusted device state persists across helper restarts.

## Related Files

- [run-openclaw-gateway-governance-e2e.sh](/home/azureuser/cloistar/scripts/run-openclaw-gateway-governance-e2e.sh)
- [manual-governance-smoke.mjs](/home/azureuser/cloistar/scripts/manual-governance-smoke.mjs)
- [openclaw-bridge-e2e-status.md](/home/azureuser/cloistar/openclaw-bridge-e2e-status.md)
