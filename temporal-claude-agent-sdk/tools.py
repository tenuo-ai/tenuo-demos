"""Fake shop: every implementation invocation is recorded before any work."""

from dataclasses import dataclass, field
from typing import Any

from policy import PREFIX


@dataclass
class Shop:
    invocations: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    refunds: list[dict[str, Any]] = field(default_factory=list)

    def get_order(self, args: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(("get_order", dict(args)))
        return {"order_id": args["order_id"], "total": 500, "status": "delivered"}

    def issue_refund(self, args: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(("issue_refund", dict(args)))
        refund = {"order_id": args["order_id"], "amount": args["amount"]}
        self.refunds.append(refund)
        return {"refunded": refund}

    def delete_order(self, args: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(("delete_order", dict(args)))
        raise AssertionError("undeclared capability reached its implementation")

    def engine_tools(self) -> dict[str, Any]:
        return {
            PREFIX + name: getattr(self, name)
            for name in ("get_order", "issue_refund", "delete_order")
        }

    def mcp_server(self) -> Any:
        from claude_agent_sdk import create_sdk_mcp_server, tool

        decorated = []
        for name, schema in [
            ("get_order", {"order_id": str}),
            ("issue_refund", {"order_id": str, "amount": int}),
            ("delete_order", {"order_id": str}),
        ]:
            implementation = getattr(self, name)

            def bind(fn: Any) -> Any:
                async def invoke(args: dict[str, Any]) -> dict[str, Any]:
                    import json

                    return {"content": [{"type": "text", "text": json.dumps(fn(args))}]}

                return invoke

            decorated.append(
                tool(name, f"Shop operation: {name}", schema)(bind(implementation))
            )
        return create_sdk_mcp_server(name="shop", version="1.0.0", tools=decorated)
