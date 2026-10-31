"""A payments MCP server with Tenuo verifying every tool call.

Pass a NonceStore to also refuse a proof of possession the server has already
accepted. Without one, the same signed call is accepted again until its
timestamp goes stale.
"""

from fastmcp import FastMCP
from tenuo import Authorizer
from tenuo.mcp import MCPVerifier, TenuoMiddleware

import fake_payments


def build_server(trusted_root, nonce_store=None, name: str = "payments") -> FastMCP:
    server = FastMCP(name)

    @server.tool
    def issue_refund(invoice_id: str, amount_cents: int, currency: str) -> str:
        """Refund part of a paid invoice. Returns the refund ID."""
        return fake_payments.refund(invoice_id, amount_cents, currency)

    verifier = MCPVerifier(
        authorizer=Authorizer(trusted_roots=[trusted_root]),
        require_warrant=True,
        nonce_store=nonce_store,
    )
    server.add_middleware(TenuoMiddleware(verifier))
    return server
