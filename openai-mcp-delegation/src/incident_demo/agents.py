"""Live OpenAI orchestrator and incident worker."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from agents import Agent, Runner, function_tool

from .authority import create_root_authority, derive_worker_authority
from .mcp_client import OperationsMCP


async def run_live_agent() -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the live agent run")
    model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

    authority = create_root_authority()
    with tempfile.TemporaryDirectory(prefix="tenuo-live-agent-") as directory:
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=Path(directory) / "operations.sqlite3",
        ) as mcp:

            @function_tool
            async def incident_investigator(request: str) -> str:
                """Investigate a checkout incident with task-scoped read authority."""
                _, _, worker_authority = derive_worker_authority(authority)

                @function_tool
                async def read_metrics(service: str) -> str:
                    """Read latency and error-rate metrics for a service."""
                    outcome = await mcp.call(
                        worker_authority,
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
                        worker_authority,
                        "read_deployment",
                        {"service": service},
                    )
                    if not outcome.allowed:
                        raise RuntimeError(outcome.error)
                    return outcome.text

                worker = Agent(
                    name="Incident investigator",
                    model=model,
                    instructions=(
                        "Investigate the checkout service using the available read tools. "
                        "Report only conclusions supported by the returned data and recommend "
                        "an operator action. The data does not include historical metrics, so "
                        "do not infer that the current deployment caused the incident or that "
                        "the previous deployment was normal. Describe a deployment regression "
                        "as a possibility, not a conclusion. Do not claim that you changed "
                        "production or can perform unavailable follow-up actions."
                    ),
                    tools=[read_metrics, read_deployment],
                )
                result = await Runner.run(worker, request)
                return str(result.final_output)

            orchestrator = Agent(
                name="Operations orchestrator",
                model=model,
                instructions=(
                    "Delegate incident investigation to the incident_investigator tool, "
                    "then give the operator a concise report."
                ),
                tools=[incident_investigator],
            )
            result = await Runner.run(
                orchestrator,
                "Investigate elevated latency in checkout and report the likely cause.",
            )
            return str(result.final_output)
