"""Authenticated ToolNode for Acts 1 & 2.

Wraps LangGraph ToolNode with the 4-layer auth pipeline (GCP SA, OAuth,
SpiceDB, OPA). Every tool call is evaluated and logged, but execution
proceeds regardless — demonstrating that all auth layers approve while
the attack succeeds.

Act 3 uses TenuoToolNode from the SDK directly (see tenuo_local.py
and tenuo_integration.py). This file is NOT used in Act 3.
"""

import time
from typing import Any, Sequence

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from agents.logger import log_tool_call, log_tool_result
from auth.pipeline import evaluate_all_layers
from server.events import publish


class AuthenticatedToolNode:
    """Drop-in ToolNode replacement that logs auth decisions for the dashboard.

    All 4 auth layers are evaluated for every tool call. Decisions are
    logged to the database and streamed via SSE. Tools always execute
    (in standard mode) so the audience can see the attack succeed while
    every auth check says ALLOW.
    """

    def __init__(
        self,
        tools: Sequence[BaseTool],
        agent_id: str = "unknown",
        auth_stack: str = "standard",
    ):
        self.tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools}
        self.agent_id = agent_id

    async def __call__(self, state: dict, config: Any = None) -> dict:
        """Process tool calls from the last AI message."""
        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None

        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {"messages": [], "events": []}

        result_messages = []
        events = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            call_id = tool_call["id"]

            # Evaluate all 4 auth layers and log decisions
            decisions = await evaluate_all_layers(self.agent_id, tool_name, tool_args)
            for d in decisions:
                event = {
                    "type": "auth_decision",
                    "agent_id": self.agent_id,
                    "tool_name": tool_name,
                    "layer": d.layer,
                    "decision": "allow" if d.allowed else "deny",
                    "reason": d.reason,
                    "latency_us": d.latency_us,
                    "timestamp": time.time(),
                }
                events.append(event)
                await publish(event)

            # Execute the tool regardless of auth decisions.
            # This is intentional — the demo shows auth passing while the attack succeeds.
            tool = self.tools_by_name.get(tool_name)
            if tool:
                try:
                    await log_tool_call(self.agent_id, tool_name, tool_args)
                    result = await tool.ainvoke(tool_args)
                    result_str = str(result)
                    await log_tool_result(self.agent_id, tool_name, result_str[:500])

                    events.append({
                        "type": "tool_call",
                        "agent_id": self.agent_id,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "result": result_str[:200],
                        "timestamp": time.time(),
                    })
                    await publish(events[-1])
                    result_messages.append(ToolMessage(content=result_str, tool_call_id=call_id))
                except Exception as e:
                    result_messages.append(
                        ToolMessage(content=f"Error: {e}", tool_call_id=call_id, status="error")
                    )
            else:
                result_messages.append(
                    ToolMessage(content=f"Tool '{tool_name}' not found.", tool_call_id=call_id, status="error")
                )

        return {"messages": result_messages, "events": events}
