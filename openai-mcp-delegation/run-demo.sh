#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "This demo requires uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

# --inexact keeps a contributor's dev extras installed.
uv sync --locked --inexact --quiet
uv run --no-sync --quiet incident-demo demo
