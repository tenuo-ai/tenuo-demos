"""The workflow owns durability; authorization remains at Activity ingress."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.claude_agent_sdk import DurableClaudeAgent


@workflow.defn
class RefundWorkflow:
    @workflow.run
    async def run(self, request: str) -> dict:
        agent = DurableClaudeAgent(
            tools=[],
            builtin_tools=[],
            tool_activities=["mcp__shop__*"],
            max_segments=8,
            auto_continue_as_new=False,
        )
        result = await agent.run(request)
        return {"result": result, "calls": agent.tool_calls}
