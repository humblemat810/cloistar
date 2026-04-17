#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-/tmp/cloister-release-check}"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

(cd "$ROOT_DIR" && python3 -c "from pathlib import Path; import setuptools.build_meta as bm; out=Path('$DIST_DIR'); print(bm.build_wheel(str(out))); print(bm.build_sdist(str(out)))")

(cd "$ROOT_DIR/plugin-governance" && npm run build)
(cd "$ROOT_DIR/plugin-kg" && npm run build)

echo "Release check passed."
