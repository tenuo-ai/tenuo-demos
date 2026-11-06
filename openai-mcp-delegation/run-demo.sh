#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "This demo requires uv: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv sync --quiet
uv run --quiet incident-demo demo
