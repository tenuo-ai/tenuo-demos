"""mcp-proxy with a Tenuo check on every tools/call.

Usage is the stock CLI, e.g.:
    TENUO_TRUSTED_ROOT=<hex public key> python tenuo_mcp_proxy.py --port 8096 -- npx @modelcontextprotocol/server-filesystem /work

Every proxied call must carry a warrant chain (in _meta.tenuo) rooted in
TENUO_TRUSTED_ROOT and a signature from the warrant's holder key. Allowed calls
are forwarded with the warrant stripped; anything else is answered by the
proxy and never reaches the server behind it.
"""

import os

import mcp.types as types
import mcp_proxy.mcp_server as mcp_server
from mcp_proxy.__main__ import main
from mcp_proxy.proxy_server import create_proxy_server
from tenuo.mcp import MCPVerifier
from tenuo_core import Authorizer, PublicKey

verifier = MCPVerifier(
    authorizer=Authorizer(trusted_roots=[PublicKey.from_bytes(bytes.fromhex(os.environ["TENUO_TRUSTED_ROOT"]))]),
    require_warrant=True,
)


async def create_guarded_proxy_server(session):
    app = await create_proxy_server(session)
    forward = app.request_handlers[types.CallToolRequest]

    async def call_tool(req: types.CallToolRequest) -> types.ServerResult:
        meta = req.params.meta.model_dump(exclude_none=True) if req.params.meta else None
        result = verifier.verify(req.params.name, req.params.arguments or {}, meta=meta)
        if not result.allowed:
            return types.ServerResult(
                types.CallToolResult(
                    content=[types.TextContent(type="text", text=f"Tenuo denied {req.params.name}: {result.denial_reason}")],
                    isError=True,
                )
            )
        clean_meta = {k: v for k, v in (meta or {}).items() if k != "tenuo"} or None
        params = req.params.model_copy(update={"arguments": result.clean_arguments, "meta": clean_meta})
        return await forward(req.model_copy(update={"params": params}))

    app.request_handlers[types.CallToolRequest] = call_tool
    return app


mcp_server.create_proxy_server = create_guarded_proxy_server

if __name__ == "__main__":
    main()
