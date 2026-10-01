#!/usr/bin/env bash
set -euo pipefail

uv run python -c 'import agents, fastmcp, tenuo; print("dependencies: ok")'
uv run incident-demo baseline
uv run incident-demo cases
