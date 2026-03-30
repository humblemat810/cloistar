#!/usr/bin/env bash
set -euo pipefail

docker compose -f docker-compose.dev.yml up --build -d
echo "Bridge is starting on http://127.0.0.1:8788"