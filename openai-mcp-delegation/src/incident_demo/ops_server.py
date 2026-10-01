"""Tenuo-protected FastMCP operations server."""

from __future__ import annotations

import json
import logging
import os
import sys

from fastmcp import FastMCP
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from tenuo import Authorizer, PublicKey
from tenuo.mcp import MCPVerifier, TenuoMiddleware

from .state import OperationsState

logging.basicConfig(
    level=logging.INFO,
    format="[operations-server] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)
logging.getLogger("fastmcp").setLevel(logging.WARNING)
logging.getLogger("tenuo").setLevel(logging.CRITICAL)


class AuthorizationAuditMiddleware(Middleware):
    """Emit one stable server-side line for every authorization decision."""

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> object:
        result = await call_next(context)
        structured = getattr(result, "structured_content", None) or {}
        tenuo = structured.get("tenuo", {}) if isinstance(structured, dict) else {}
        if isinstance(tenuo, dict) and tenuo:
            reason = tenuo.get("message", "Authorization denied")
            if "Proof-of-Possession verification failed" in reason:
                reason = "Proof-of-Possession verification failed"
            log.warning("DENIED %s: %s", context.message.name, reason)
        elif getattr(result, "is_error", False):
            log.error("ERROR %s: tool execution failed", context.message.name)
        else:
            log.info("ALLOWED %s", context.message.name)
        return result


def create_server() -> FastMCP:
    root_hex = os.environ.get("TENUO_DEMO_ISSUER_PUBLIC_KEY")
    state_path = os.environ.get("TENUO_DEMO_STATE_PATH")
    if not root_hex or not state_path:
        raise RuntimeError(
            "TENUO_DEMO_ISSUER_PUBLIC_KEY and TENUO_DEMO_STATE_PATH are required"
        )

    authorizer = Authorizer(
        trusted_roots=[PublicKey.from_bytes(bytes.fromhex(root_hex))],
        clock_tolerance_secs=0,
    )
    verifier = MCPVerifier(authorizer=authorizer, require_warrant=True)
    state = OperationsState(state_path)
    mcp = FastMCP(
        "operations",
        middleware=[AuthorizationAuditMiddleware(), TenuoMiddleware(verifier)],
    )

    @mcp.tool()
    async def read_metrics(service: str) -> str:
        """Read current latency and error-rate metrics for a service."""
        snapshot = state.as_dict(service)
        log.info("EXECUTED read_metrics service=%s", service)
        return json.dumps(
            {
                "service": service,
                "p95_latency_ms": snapshot["p95_latency_ms"],
                "error_rate": snapshot["error_rate"],
            },
            sort_keys=True,
        )

    @mcp.tool()
    async def read_deployment(service: str) -> str:
        """Read the active and previous deployment for a service."""
        log.info("EXECUTED read_deployment service=%s", service)
        return json.dumps(state.as_dict(service), sort_keys=True)

    @mcp.tool()
    async def rollback_deployment(service: str, deployment: str) -> str:
        """Roll back the active deployment for a service."""
        result = state.rollback(service, deployment)
        log.info(
            "EXECUTED rollback_deployment service=%s deployment=%s",
            service,
            deployment,
        )
        return json.dumps(state.as_dict(result.service), sort_keys=True)

    return mcp


def main() -> None:
    create_server().run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
