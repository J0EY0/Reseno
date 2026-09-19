#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
image_file=$(mktemp)
trap 'rm -f "$image_file"' EXIT

DOCKER_BUILDKIT=1 docker build \
  --file "$repo_root/.github/Dockerfile.browser" \
  --build-arg "NODE_VERSION=$(cat "$repo_root/frontend/.node-version")" \
  --iidfile "$image_file" \
  "$repo_root"

mkdir -p "$repo_root/backend/test-results"
docker run --rm --init --ipc=host \
  --mount "type=bind,source=$repo_root/backend/test-results,target=/workspace/backend/test-results" \
  "$(cat "$image_file")"
