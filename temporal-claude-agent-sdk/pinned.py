"""The draft plugin commit this example runs against, read from requirements.txt."""

import re
from pathlib import Path

PLUGIN_REPO = "https://github.com/osamastro7-droid/ai-integrations"
PLUGIN_COMMIT = re.search(
    r"ai-integrations@([0-9a-f]{40})",
    (Path(__file__).parent / "requirements.txt").read_text(),
).group(1)
