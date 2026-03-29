"""Combined tool node for Act 3 — standard auth logging + Tenuo enforcement.

Runs all 4 standard auth layers (for the dashboard) AND checks Tenuo
warrant constraints. The audience sees:
  - 4 green checkmarks (standard auth passes, as always)
  - 1 red X (Tenuo catches the constraint violation)

This wraps TenuoToolNode so all enforcement is done by the real SDK.
The standard auth pipeline runs for display only — it doesn't affect execution.
"""

import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from agents.logger import log_tool_call, log_tool_result, log_status
from auth.pipeline import evaluate_all_layers
from server.events import publish

logger = logging.getLogger(__name__)


class TenuoAuthenticatedToolNode:
    """Tool node that shows both standard auth (all ALLOW) and Tenuo enforcement."""

    def __init__(self, tenuo_tool_node: Any, agent_id: str = "unknown"):
        self.tenuo_node = tenuo_tool_node
        self.agent_id = agent_id

    async def __call__(self, state: dict, config: Any = None) -> dict:
        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None

        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {"messages": [], "events": []}

        events = []
        tool_calls = last_message.tool_calls

        # Step 1: Run standard auth pipeline for DISPLAY
        for tc in tool_calls:
            decisions = await evaluate_all_layers(self.agent_id, tc["name"], tc["args"])
            for d in decisions:
                event = {
                    "type": "auth_decision",
                    "agent_id": self.agent_id,
                    "tool_name": tc["name"],
                    "layer": d.layer,
                    "decision": "allow" if d.allowed else "deny",
                    "reason": d.reason,
                    "latency_us": d.latency_us,
                    "timestamp": time.time(),
                }
                events.append(event)
                await publish(event)

        # Step 2: Pre-check warrant constraints to measure pure check time
        # Then delegate to TenuoToolNode for actual enforcement
        warrant_b64 = state.get("warrant", "")
        check_latencies: dict[str, int] = {}
        if warrant_b64:
            try:
                from tenuo_core import Warrant
                w = Warrant.from_base64(warrant_b64)
                for tc in tool_calls:
                    start_ns = time.perf_counter_ns()
                    w.check_constraints(tc["name"], tc["args"])
                    check_latencies[tc.get("id", "")] = (time.perf_counter_ns() - start_ns) // 1000
            except Exception:
                pass

        result = await self.tenuo_node.ainvoke(state, config)

        # Step 3: Match result messages to tool calls and log Tenuo decisions
        # TenuoToolNode returns {"messages": [ToolMessage, ...]}
        result_messages = result.get("messages", [])

        # Build a map from tool_call_id to result message
        result_by_id = {}
        for msg in result_messages:
            if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id"):
                result_by_id[msg.tool_call_id] = msg

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            call_id = tc.get("id", "")

            msg = result_by_id.get(call_id)
            if msg is None:
                continue

            content = (msg.content or "").lower()
            status = getattr(msg, "status", None)
            is_auth_denied = status == "error" and (
                "authorization denied" in content
                or "security configuration error" in content
            )

            if is_auth_denied:
                reason = f"Warrant constraint violation on '{tool_name}'"
                await log_status(
                    self.agent_id,
                    f"Tenuo DENIED {tool_name}: {msg.content}",
                    tool_name=tool_name,
                )
            else:
                reason = "Warrant authorizes tool call"
                await log_tool_call(self.agent_id, tool_name, tool_args)
                if status != "error":
                    await log_tool_result(self.agent_id, tool_name, str(msg.content)[:500])

            # Log Tenuo decision with pure constraint-check latency
            check_us = check_latencies.get(call_id, 0)
            tenuo_event = {
                "type": "auth_decision",
                "agent_id": self.agent_id,
                "tool_name": tool_name,
                "layer": "tenuo",
                "decision": "deny" if is_auth_denied else "allow",
                "reason": reason,
                "latency_us": check_us,
                "timestamp": time.time(),
            }
            events.append(tenuo_event)
            await publish(tenuo_event)

            # Also write to auth_decisions DB table
            try:
                from tools.db import get_pool
                import json
                pool = await get_pool()
                await pool.execute(
                    """INSERT INTO auth_decisions
                       (request_id, agent_id, tool_name, tool_args, layer, decision, reason, latency_us)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    call_id or "unknown",
                    self.agent_id,
                    tool_name,
                    json.dumps(tool_args),
                    "tenuo",
                    "deny" if is_auth_denied else "allow",
                    reason,
                    check_us,
                )
            except Exception:
                pass

        existing_events = result.get("events", [])
        return {**result, "events": existing_events + events}
