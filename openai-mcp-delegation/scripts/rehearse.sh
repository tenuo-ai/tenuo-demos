#!/usr/bin/env bash
set -euo pipefail

uv run incident-demo baseline

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  uv run incident-demo agent
else
  echo "OPENAI_API_KEY is not set; skipped live agent run"
fi

uv run incident-demo cases
