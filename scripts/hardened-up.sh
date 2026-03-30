#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
  echo "Missing .env. Start from .env.example before running the hardened stack." >&2
  exit 1
fi

mkdir -p .docker/openclaw-config .docker/openclaw-workspace

DOCKER_BUILDKIT=1 docker build \
  -t kogwistar-openclaw:local \
  --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1 \
  -f openclaw/Dockerfile \
  ./openclaw

DOCKER_BUILDKIT=1 docker build \
  -t openclaw-sandbox:bookworm-slim \
  -f openclaw/Dockerfile.sandbox \
  ./openclaw

docker compose -f docker-compose.hardened.yml build bridge
docker compose -f docker-compose.hardened.yml up -d --no-build
