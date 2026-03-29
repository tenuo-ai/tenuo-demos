"""Shared types for the auth pipeline."""

from dataclasses import dataclass
from typing import Any


@dataclass
class AuthRequest:
    """A tool call authorization request."""

    agent_id: str
    tool_name: str
    tool_args: dict[str, Any]
    request_id: str = ""


@dataclass
class AuthDecision:
    """A single auth layer's decision."""

    layer: str
    allowed: bool
    reason: str
    latency_us: int = 0
