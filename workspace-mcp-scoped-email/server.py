"""Workspace MCP with Tenuo verifying every tool call.

This is the whole server-side change: one middleware, installed first so it
sees the arguments exactly as the client signed them. Calls without a valid
warrant are refused before any Google API is touched.
"""

from core.server import server
import gmail.gmail_tools  # noqa: F401  (registers the Gmail tools on `server`)
from tenuo.mcp import MCPVerifier, TenuoMiddleware
from tenuo_core import Authorizer


def build_server(trusted_root):
    verifier = MCPVerifier(authorizer=Authorizer(trusted_roots=[trusted_root]), require_warrant=True)
    server.middleware.insert(0, TenuoMiddleware(verifier))
    return server
