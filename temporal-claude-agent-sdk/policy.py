"""Task warrant and pure dispatcher mapping; no Claude-specific code in Tenuo."""

from collections.abc import Sequence
from typing import Any

from tenuo import Exact, Range, SigningKey, Warrant
from tenuo.temporal import TenuoPluginConfig
from tenuo.temporal._dedup import InMemoryPopDedupStore

PREFIX = "mcp__shop__"
TOOL_ACTIVITY = "run_claude_tool_step"
SEGMENT_ACTIVITY = "run_claude_segment"


def logical_call(args: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    if len(args) != 1:
        raise ValueError("expected one ToolStepInput")
    step = args[0]
    call = step["call"] if isinstance(step, dict) else step.call
    name = call["name"] if isinstance(call, dict) else call.name
    arguments = call["input"] if isinstance(call, dict) else call.input
    kind = call.get("kind", "durable") if isinstance(call, dict) else call.kind
    if kind != "engine" or not isinstance(name, str) or not name.startswith(PREFIX):
        raise ValueError("expected a shop MCP engine tool")
    if not isinstance(arguments, dict):
        raise TypeError("tool input must be a dictionary")
    # Remove only this server's transport prefix. Unknown names still reach the
    # authorizer and are denied by the warrant's closed capability set.
    return name[len(PREFIX) :], dict(arguments)


def segment_call(args: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    if len(args) != 1:
        raise ValueError("expected one SegmentInput")
    inp = args[0]
    get = inp.get if isinstance(inp, dict) else lambda key: getattr(inp, key)
    if get("builtin_tools") or get("tools"):
        raise ValueError("this demo permits no inline or durable tools")
    if list(get("tool_activities")) != [PREFIX + "*"]:
        raise ValueError("all shop tools must pause for their own Activity")
    return SEGMENT_ACTIVITY, {}


def task_warrant(
    issuer: SigningKey,
    holder: SigningKey,
    *,
    workflow_id: str | None = None,
    order_id: str = "order-123",
    limit: int = 100,
    ttl: int = 600,
) -> Warrant:
    builder = (
        Warrant.mint_builder()
        .holder(holder.public_key)
        .capability(SEGMENT_ACTIVITY, {})
        .capability("get_order", order_id=Exact(order_id))
        .capability(
            "issue_refund", order_id=Exact(order_id), amount=Range(min=0, max=limit)
        )
        .ttl(ttl)
    )
    if workflow_id is not None:
        builder.session_id(workflow_id)
    return builder.mint(issuer)


def plugin_config(
    issuer: SigningKey, holder: SigningKey, **kwargs: Any
) -> TenuoPluginConfig:
    return TenuoPluginConfig(
        signing_key=holder,
        trusted_roots=[issuer.public_key],
        pop_dedup_store=InMemoryPopDedupStore(),
        **kwargs,
    )


def resolve_call(activity_type: str, args: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    """Map only this PoC's two Activity envelopes; reject malformed requests."""
    from tenuo.temporal._pop import _normalize_args_for_pop
    from tenuo.temporal.exceptions import TenuoContextError

    try:
        resolver = {TOOL_ACTIVITY: logical_call, SEGMENT_ACTIVITY: segment_call}[
            activity_type
        ]
        name, arguments = resolver(args)
        if not name or not all(isinstance(key, str) for key in arguments):
            raise ValueError("expected a tool name and string argument keys")
        return name, _normalize_args_for_pop(arguments)
    except Exception as exc:
        raise TenuoContextError(f"Cannot resolve {activity_type}: {exc}") from exc
