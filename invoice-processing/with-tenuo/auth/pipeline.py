"""Auth decision pipeline — chains all 4 layers and logs decisions.

Every tool call passes through all 4 auth layers in sequence. Every
decision is logged to the database AND emitted as an SSE event for
the dashboard. The key demo visual: all 4 show green checkmarks while
the attack succeeds.
"""

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from auth.gcp_sa import check_gcp_sa
from auth.oauth import check_oauth
from auth.opa import check_opa
from auth.spicedb import check_spicedb
from auth.types import AuthDecision, AuthRequest
from tools.db import get_pool


async def evaluate_all_layers(
    agent_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    request_id: str | None = None,
) -> list[AuthDecision]:
    """Run all 4 auth layers and return their decisions.

    All layers are evaluated regardless of earlier results — we want
    to show the audience every layer's decision for every tool call.

    Pass request_id to share the same ID with a Tenuo layer decision so
    all layers for a single tool call appear in one row in the dashboard.
    """
    request = AuthRequest(
        agent_id=agent_id,
        tool_name=tool_name,
        tool_args=tool_args,
        request_id=request_id or str(uuid.uuid4()),
    )

    decisions = []

    # Layer 1: GCP Service Account
    decisions.append(check_gcp_sa(request))

    # Layer 2: OAuth 2.0
    decisions.append(check_oauth(request))

    # Layer 3: SpiceDB (Zanzibar RBAC)
    decisions.append(check_spicedb(request))

    # Layer 4: OPA Policy Engine
    decisions.append(await check_opa(request))

    # Log all decisions to database
    await _log_decisions(request, decisions)

    return decisions


async def is_allowed(
    agent_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
) -> tuple[bool, list[AuthDecision]]:
    """Check if a tool call is allowed by all 4 layers.

    Returns (allowed, decisions) — allowed is True only if ALL layers agree.
    """
    decisions = await evaluate_all_layers(agent_id, tool_name, tool_args)
    all_allowed = all(d.allowed for d in decisions)
    return all_allowed, decisions


async def _log_decisions(request: AuthRequest, decisions: list[AuthDecision]):
    """Log auth decisions to the database for dashboard display."""
    try:
        pool = await get_pool()
        for decision in decisions:
            await pool.execute(
                """INSERT INTO auth_decisions
                   (request_id, agent_id, tool_name, tool_args, layer, decision, reason, latency_us)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                request.request_id,
                request.agent_id,
                request.tool_name,
                json.dumps(request.tool_args),
                decision.layer,
                "allow" if decision.allowed else "deny",
                decision.reason,
                decision.latency_us,
            )
    except Exception as e:
        logger.warning(f"Failed to log auth decision: {e}")
