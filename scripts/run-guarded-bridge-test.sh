#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  cat <<'EOF'
Usage:
  scripts/run-guarded-bridge-test.sh <python-test-name> [timeout-seconds]

Example:
  scripts/run-guarded-bridge-test.sh \
    bridge.tests.test_bridge_contract.BridgeContractTests.test_approval_resolution_appends_resolution_and_resume_events \
    10
EOF
  exit 2
fi

TEST_NAME="$1"
TIMEOUT_SECONDS="${2:-10}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: missing python interpreter at ${PYTHON_BIN}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

"${PYTHON_BIN}" - <<'PY' "${TEST_NAME}" "${TIMEOUT_SECONDS}"
import faulthandler
import sys
import unittest

test_name = sys.argv[1]
timeout_seconds = int(sys.argv[2])

faulthandler.enable()
faulthandler.dump_traceback_later(timeout_seconds, repeat=False)

try:
    suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
finally:
    faulthandler.cancel_dump_traceback_later()

raise SystemExit(0 if result.wasSuccessful() else 1)
PY
