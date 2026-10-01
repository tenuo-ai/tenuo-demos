"""Live OpenAI orchestrator and incident worker."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agents import Agent, Runner, function_tool

from .authority import create_authority
from .mcp_client import OperationsMCP


async def run_live_agent() -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the live agent run")

    authority = create_authority()
    with tempfile.TemporaryDirectory(prefix="tenuo-live-agent-") as directory:
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=Path(directory) / "operations.sqlite3",
        ) as mcp:

            @function_tool
            async def read_metrics(service: str) -> str:
                """Read latency and error-rate metrics for a service."""
                outcome = await mcp.call(
                    authority.delegated_worker,
                    "read_metrics",
                    {"service": service},
                )
                if not outcome.allowed:
                    raise RuntimeError(outcome.error)
                return outcome.text

            @function_tool
            async def read_deployment(service: str) -> str:
                """Read the active and previous deployment for a service."""
                outcome = await mcp.call(
                    authority.delegated_worker,
                    "read_deployment",
                    {"service": service},
                )
                if not outcome.allowed:
                    raise RuntimeError(outcome.error)
                return outcome.text

            model = os.environ.get("OPENAI_MODEL") or None
            worker = Agent(
                name="Incident investigator",
                model=model,
                instructions=(
                    "Investigate the checkout service using the available read tools. "
                    "Report the likely cause and recommend an action. Do not claim that "
                    "you changed production."
                ),
                tools=[read_metrics, read_deployment],
            )
            orchestrator = Agent(
                name="Operations orchestrator",
                model=model,
                instructions=(
                    "Delegate incident investigation to the incident_investigator tool, "
                    "then give the operator a concise report."
                ),
                tools=[
                    worker.as_tool(
                        tool_name="incident_investigator",
                        tool_description="Investigate checkout incidents with read-only authority.",
                    )
                ],
            )
            result = await Runner.run(
                orchestrator,
                "Investigate elevated latency in checkout and report the likely cause.",
            )
            return str(result.final_output)
