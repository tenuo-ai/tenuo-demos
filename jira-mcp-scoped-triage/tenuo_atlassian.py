"""mcp-atlassian with a Tenuo check on every tool call.

Usage is the stock CLI, e.g.:
    TENUO_TRUSTED_ROOT=<hex public key> python tenuo_atlassian.py

Every call must carry a warrant chain (in _meta.tenuo) rooted in
TENUO_TRUSTED_ROOT and a signature from the warrant's holder key. Anything
else is refused before the tool runs, so it never reaches Jira.
"""

import os

from mcp_atlassian import main
from mcp_atlassian.servers import main_mcp
from tenuo.mcp import MCPVerifier, TenuoMiddleware
from tenuo_core import Authorizer, PublicKey

root = PublicKey.from_bytes(bytes.fromhex(os.environ["TENUO_TRUSTED_ROOT"]))
verifier = MCPVerifier(authorizer=Authorizer(trusted_roots=[root]), require_warrant=True)
main_mcp.middleware.insert(0, TenuoMiddleware(verifier))

if __name__ == "__main__":
    main()
