"""Event emission helpers for dashboard streaming."""

import time
from typing import Any


def emit_event(event_type: str, agent_id: str, **data: Any) -> dict:
    """Create a dashboard event dict to be accumulated in state.events."""
    return {
        "type": event_type,
        "agent_id": agent_id,
        "timestamp": time.time(),
        **data,
    }


def tool_call_event(agent_id: str, tool_name: str, tool_args: dict, result: str | None = None) -> dict:
    return emit_event("tool_call", agent_id, tool_name=tool_name, tool_args=tool_args, result=result)


def auth_decision_event(
    agent_id: str, tool_name: str, layer: str, decision: str, reason: str = "", latency_us: int = 0
) -> dict:
    return emit_event(
        "auth_decision",
        agent_id,
        tool_name=tool_name,
        layer=layer,
        decision=decision,
        reason=reason,
        latency_us=latency_us,
    )


def agent_status_event(agent_id: str, status: str, **data: Any) -> dict:
    return emit_event("agent_status", agent_id, status=status, **data)


def delegation_event(parent_id: str, child_id: str, tools: list[str], ttl_minutes: int) -> dict:
    return emit_event(
        "delegation",
        parent_id,
        child_id=child_id,
        delegated_tools=tools,
        ttl_minutes=ttl_minutes,
    )
