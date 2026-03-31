#!/usr/bin/env bash
set -euo pipefail

# Switch between baseline (no Tenuo) and with-tenuo modes.
# Creates symlinks so the server imports from the right folder.
#
# Usage:
#   ./scripts/switch-mode.sh baseline    # Acts 1 & 2
#   ./scripts/switch-mode.sh with-tenuo  # Act 3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEMO_DIR="$(dirname "$SCRIPT_DIR")"
MODE="${1:-baseline}"

if [ "$MODE" != "baseline" ] && [ "$MODE" != "with-tenuo" ]; then
    echo "Usage: $0 [baseline|with-tenuo]"
    exit 1
fi

cd "$DEMO_DIR"

# Remove existing symlinks
rm -f agents auth tools

if [ "$MODE" = "baseline" ]; then
    ln -s baseline/agents agents
    ln -s baseline/auth auth
    ln -s baseline/tools tools
    echo "Mode: baseline (standard auth only)"
else
    # Start with baseline, overlay with-tenuo changes
    # Use a merged directory approach
    rm -rf _merged
    cp -r baseline _merged
    # Overlay with-tenuo files (only the ones that change)
    cp -r with-tenuo/agents/* _merged/agents/
    cp -r with-tenuo/auth/* _merged/auth/
    ln -s _merged/agents agents
    ln -s _merged/auth auth
    ln -s _merged/tools tools  # tools don't change
    echo "Mode: with-tenuo (Tenuo protection enabled)"
fi
