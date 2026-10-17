import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Match upstream's isolation: real engines must only use the local fake API,
# regardless of provider credentials/settings on the machine running pytest.
for key in list(os.environ):
    if key.startswith(("CLAUDE", "ANTHROPIC")) and key != "CLAUDE_CLI_PATH":
        del os.environ[key]
