#!/usr/bin/env bash
# Isolated end-to-end run with a temporary local Temporal server.
set -euo pipefail

example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
run_dir="$(mktemp -d "${TMPDIR:-/tmp}/tenuo-claude-e2e.XXXXXX")"
export UV_NO_EDITABLE=1
port="${TEMPORAL_DEMO_PORT:-17333}"
server_pid=""

cleanup() {
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    echo "Run artifacts: $run_dir"
}
trap cleanup EXIT

for executable in uv git temporal; do
    command -v "$executable" >/dev/null || { echo "Missing command: $executable" >&2; exit 1; }
done

uv venv "$run_dir/venv"
python="$run_dir/venv/bin/python"
uv pip install --python "$python" -r "$example_dir/requirements.txt"

# The real-engine tests reuse the plugin's own local Messages API simulator,
# from the same pinned commit as the installed plugin.
read -r repo commit < <(cd "$example_dir" && "$python" -c \
    'from pinned import PLUGIN_REPO, PLUGIN_COMMIT; print(PLUGIN_REPO, PLUGIN_COMMIT)')
checkout="$run_dir/ai-integrations"
git init -q "$checkout"
git -C "$checkout" fetch -q --depth 1 "$repo" "$commit"
git -C "$checkout" checkout -q FETCH_HEAD

temporal server start-dev --ip 127.0.0.1 --port "$port" --headless >"$run_dir/server.log" 2>&1 &
server_pid=$!
export TEMPORAL_ADDRESS="127.0.0.1:$port"
export AI_INTEGRATIONS_CHECKOUT="$checkout"
unset PYTHONPATH

"$python" - <<'PY'
import asyncio
import os
from temporalio.client import Client

async def ready():
    for _ in range(45):
        try:
            await asyncio.wait_for(Client.connect(os.environ["TEMPORAL_ADDRESS"]), 1)
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError("Temporal did not become ready; inspect server.log in the run artifacts")

asyncio.run(ready())
PY
kill -0 "$server_pid" 2>/dev/null || { cat "$run_dir/server.log" >&2; exit 1; }

cd "$example_dir"
"$python" -c 'import tenuo; print("Tenuo:", tenuo.__version__, tenuo.__file__)'
"$python" -m pytest -q tests --junitxml="$run_dir/results.xml"
"$python" run_lifecycle.py --address "$TEMPORAL_ADDRESS" --restart | tee "$run_dir/lifecycle.log"
