"""Deterministic stage cases using the real MCP transport and server."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tenuo import Exact

from .authority import PresentedAuthority, create_authority
from .mcp_client import OperationsMCP, ToolOutcome


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    expected: str
    outcome: ToolOutcome


async def run_baseline(*, show: bool = True) -> list[ScenarioResult]:
    """Establish tool-level task scope before introducing delegation."""
    authority = create_authority()
    state_dir = tempfile.TemporaryDirectory(prefix="tenuo-tool-scope-demo-")
    state_path = Path(state_dir.name) / "operations.sqlite3"

    try:
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=state_path,
        ) as mcp:
            allowed = await mcp.call(
                authority.orchestrator,
                "read_metrics",
                {"service": "checkout"},
            )
            denied = await mcp.call(
                authority.orchestrator,
                "read_metrics",
                {"service": "payments"},
            )
    finally:
        state_dir.cleanup()

    results = [
        ScenarioResult("read checkout metrics", "ALLOW", allowed),
        ScenarioResult("read payments metrics", "DENY", denied),
    ]
    if show:
        print("\nTool-level task scope over MCP\n")
        for index, result in enumerate(results, start=1):
            actual = "ALLOW" if result.outcome.allowed else "DENY"
            mark = "PASS" if actual == result.expected else "FAIL"
            detail = result.outcome.text if result.outcome.allowed else result.outcome.error
            print(f"{index}. [{mark}] {result.name:22} expected={result.expected} actual={actual}")
            if detail:
                print(f"   {detail}")

    return results


async def run_cases(*, show: bool = True) -> list[ScenarioResult]:
    authority = create_authority()
    state_dir = tempfile.TemporaryDirectory(prefix="tenuo-incident-demo-")
    state_path = Path(state_dir.name) / "operations.sqlite3"
    results: list[ScenarioResult] = []

    try:
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=state_path,
        ) as mcp:
            read = await mcp.call(
                authority.delegated_worker,
                "read_deployment",
                {"service": "checkout"},
            )
            results.append(ScenarioResult("delegated read", "ALLOW", read))

            rollback = await mcp.call(
                authority.delegated_worker,
                "rollback_deployment",
                {"service": "checkout", "deployment": "8c1e"},
            )
            results.append(ScenarioResult("worker rollback", "DENY", rollback))

            detached = await mcp.call(
                authority.delegated_worker.detached(),
                "read_deployment",
                {"service": "checkout"},
            )
            results.append(ScenarioResult("child without parent", "DENY", detached))

            # Keep the same trusted root and derive a deliberately short-lived
            # worker warrant from it.
            expired_child = (
                authority.root.grant_builder()
                .capability("read_deployment", service=Exact("checkout"))
                .holder(authority.worker_key.public_key)
                .ttl(1)
                .grant(authority.orchestrator_key)
            )
            expired_authority = PresentedAuthority(
                (authority.root, expired_child), authority.worker_key
            )
            await asyncio.sleep(1.2)
            expired = await mcp.call(
                expired_authority,
                "read_deployment",
                {"service": "checkout"},
            )
            results.append(ScenarioResult("expired child", "DENY", expired))

            state = await mcp.call(
                authority.delegated_worker,
                "read_deployment",
                {"service": "checkout"},
            )
            snapshot = json.loads(state.text)
            if snapshot["deployment"] != "8c1e" or snapshot["rollbacks_executed"] != 0:
                raise AssertionError("denied rollback changed operations state")
    finally:
        state_dir.cleanup()

    if show:
        print("\nTask-scoped authorization over MCP\n")
        for index, result in enumerate(results, start=1):
            actual = "ALLOW" if result.outcome.allowed else "DENY"
            mark = "PASS" if actual == result.expected else "FAIL"
            detail = result.outcome.text if result.outcome.allowed else result.outcome.error
            print(f"{index}. [{mark}] {result.name:22} expected={result.expected} actual={actual}")
            if detail:
                print(f"   {detail}")
        print("\nProtected state: deployment=8c1e, rollbacks_executed=0")

    return results
