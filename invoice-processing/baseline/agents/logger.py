"""Agent activity logger — writes rich traces to agent_logs table.

Every agent action (LLM reasoning, tool calls, tool results, delegations)
is logged here for the dashboard activity feed. This replaces the SSE-based
approach with reliable DB-backed logging.
"""

import json
import uuid
from typing import Any

from tools.db import get_pool

# Global run ID — set per demo run so we can filter logs
_current_run_id: str = ""


def new_run() -> str:
    """Start a new run and return its ID."""
    global _current_run_id
    _current_run_id = f"run-{uuid.uuid4().hex[:8]}"
    return _current_run_id


def get_run_id() -> str:
    global _current_run_id
    if not _current_run_id:
        new_run()
    return _current_run_id


async def log_event(
    agent_id: str,
    event_type: str,
    content: str = "",
    tool_name: str | None = None,
    tool_args: dict | None = None,
    metadata: dict | None = None,
):
    """Log an agent event to the database."""
    try:
        pool = await get_pool()
        await pool.execute(
            """INSERT INTO agent_logs (run_id, agent_id, event_type, content, tool_name, tool_args, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            get_run_id(),
            agent_id,
            event_type,
            content[:2000] if content else None,  # Truncate long content
            tool_name,
            json.dumps(tool_args) if tool_args else None,
            json.dumps(metadata) if metadata else None,
        )
    except Exception:
        pass  # Don't break the pipeline if logging fails


def extract_text(content) -> str:
    """Extract readable text from LangChain message content.

    Content can be a string or a list of content blocks like:
    [{"text": "...", "type": "text"}, {"type": "tool_use", ...}]
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else ""
    return str(content)


async def log_thinking(agent_id: str, content, **meta: Any):
    """Log agent LLM reasoning/response."""
    text = extract_text(content)
    if text:
        await log_event(agent_id, "thinking", text, metadata=meta if meta else None)


async def log_tool_call(agent_id: str, tool_name: str, tool_args: dict, **meta: Any):
    """Log a tool call."""
    await log_event(agent_id, "tool_call", tool_name=tool_name, tool_args=tool_args,
                    metadata=meta if meta else None)


async def log_tool_result(agent_id: str, tool_name: str, result: str, **meta: Any):
    """Log a tool result."""
    await log_event(agent_id, "tool_result", content=result, tool_name=tool_name,
                    metadata=meta if meta else None)


async def log_delegation(parent_id: str, child_id: str, tools: list[str], **meta: Any):
    """Log a delegation from parent to child agent."""
    await log_event(parent_id, "delegation",
                    content=f"Delegating to {child_id} with tools: {', '.join(tools)}",
                    metadata={"child_id": child_id, "tools": tools, **(meta or {})})


async def log_status(agent_id: str, status: str, **meta: Any):
    """Log an agent status change."""
    await log_event(agent_id, "status", content=status, metadata=meta if meta else None)
