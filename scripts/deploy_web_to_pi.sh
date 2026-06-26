#!/usr/bin/env bash
#
# Cross-build the FIMS frontend (web) image for the Pi's arm64 architecture on a
# faster x86 machine, then ship the built image to the Pi so the Pi never has to
# compile Vite itself. Replaces the slow `docker compose build web` on the Pi.
#
# Flow:  PC (buildx, linux/arm64)  ->  docker save | ssh | docker load  ->  Pi restarts container
#
# Usage:   bash scripts/deploy_web_to_pi.sh
#
# Override any of these via environment variables if needed:
set -euo pipefail

PI_HOST="${PI_HOST:-krioasns@100.73.208.99}"
PI_REPO="${PI_REPO:-~/fims}"
IMAGE="${IMAGE:-fims-web:latest}"
PLATFORM="${PLATFORM:-linux/arm64}"
# These MUST match docker-compose.yml's web.build.args, since Vite bakes them in.
VITE_API_URL="${VITE_API_URL:-/api}"
VITE_RECEIPT_BASE_URL="${VITE_RECEIPT_BASE_URL:-https://kianpotpi.taile4f97e.ts.net}"

# Resolve the frontend context relative to this script, so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT="${SCRIPT_DIR}/../frontend"

echo "==> Building ${IMAGE} for ${PLATFORM} on this machine"
docker buildx build \
  --platform "${PLATFORM}" \
  --build-arg "VITE_API_URL=${VITE_API_URL}" \
  --build-arg "VITE_RECEIPT_BASE_URL=${VITE_RECEIPT_BASE_URL}" \
  -t "${IMAGE}" \
  --load \
  "${CONTEXT}"

echo "==> Shipping image to ${PI_HOST} (save | gzip | ssh | load)"
docker save "${IMAGE}" | gzip | ssh -o BatchMode=yes "${PI_HOST}" 'gunzip | docker load'

echo "==> Restarting web container on the Pi (no rebuild)"
ssh -o BatchMode=yes "${PI_HOST}" "cd ${PI_REPO} && docker compose up -d --no-build web"

echo "==> Done. Live bundle:"
ssh -o BatchMode=yes "${PI_HOST}" 'docker exec fims-web-1 sh -c "grep -o \"assets/index-[A-Za-z0-9_-]*\.js\" /app/dist/index.html"'
