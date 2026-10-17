"""Durable approval and authority state; no issuing or signing keys here."""

import json

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from adapter import warrant_scope
    from tenuo.temporal._headers import _current_workflow_headers

    from temporalio.claude_agent_sdk import DurableClaudeAgent


@workflow.defn
class LifecycleWorkflow:
    def __init__(self):
        self.authority_headers: dict[str, bytes] = {}
        self.phase = "starting"
        self.approved: bool | None = None
        self.replacement: dict[str, bytes] | None = None
        self.retry_requested = False
        self.calls = []

    @workflow.query
    def status(self) -> dict:
        return {"phase": self.phase, "calls": self.calls}

    @workflow.update
    def approve_refund(self, approved: bool) -> None:
        if self.phase != "awaiting approval" or self.approved is not None:
            raise ValueError("no refund is awaiting approval")
        self.approved = approved

    @workflow.update
    def install_authority(self, headers: dict[str, bytes]) -> None:
        if (
            self.phase != "awaiting authority"
            or not self.approved
            or self.replacement is not None
        ):
            raise ValueError("approval must precede controller authority installation")
        # Only issued public warrant headers; the Activity Worker verifies them.
        # This Update is a controller API, never a Claude tool. Temporal
        # authenticates callers.
        self.replacement = headers

    @workflow.update
    def retry_refund(self) -> None:
        if self.phase != "authority installed":
            raise ValueError("install controller authority before requesting a retry")
        self.retry_requested = True

    async def ask(self, name: str, order_id: str, amount: int | None = None):
        agent = DurableClaudeAgent(
            tools=[],
            builtin_tools=[],
            tool_activities=["mcp__shop__*"],
            max_segments=4,
            auto_continue_as_new=False,
        )
        args = {"order_id": order_id}
        if amount is not None:
            args["amount"] = amount
        # Every Activity of this run is signed, when scheduled, with the
        # authority current at its start.
        with warrant_scope(self.authority_headers):
            await agent.run(json.dumps({"name": name, "input": args}))
        self.calls.extend(agent.tool_calls)

    @workflow.run
    async def run(self, order_id: str) -> dict:
        self.authority_headers = dict(_current_workflow_headers())
        await self.ask("get_order", order_id)
        await self.ask("issue_refund", order_id, 25)
        await self.ask("issue_refund", order_id, 250)
        self.phase = "awaiting approval"
        workflow.logger.info("[workflow] requesting approval for refund 250")
        await workflow.wait_condition(lambda: self.approved is not None)
        if not self.approved:
            self.phase = "approval declined"
            return self.status()
        # Demonstrate that a recorded approval alone leaves authority unchanged.
        await self.ask("issue_refund", order_id, 250)
        self.phase = "awaiting authority"
        await workflow.wait_condition(lambda: self.replacement is not None)
        self.authority_headers = self.replacement
        self.phase = "authority installed"
        await workflow.wait_condition(lambda: self.retry_requested)
        await self.ask("issue_refund", order_id, 250)
        self.phase = "complete"
        return self.status()
