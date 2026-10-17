"""Ensure tests exercise the plugin build pinned in requirements.txt."""

import json
from importlib.metadata import distribution

from pinned import PLUGIN_COMMIT


def test_installed_plugin_is_the_pinned_commit():
    direct = json.loads(
        distribution("temporalio-claude-agent-sdk").read_text("direct_url.json")
    )
    assert direct["vcs_info"]["commit_id"] == PLUGIN_COMMIT
