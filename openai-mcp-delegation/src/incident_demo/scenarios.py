"""Deterministic stage cases using the real MCP transport and server."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tenuo import Exact, SigningKey

from .authority import PresentedAuthority, create_authority
from .mcp_client import OperationsMCP, ToolOutcome


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    expected: str
    outcome: ToolOutcome


def _show_case(index: int, name: str) -> None:
    print(f"\n{index}. CASE  {name}", flush=True)


def _pause_for_stage(message: str) -> None:
    """Let the presenter establish the claim before the call executes."""
    print(f"   WATCH  {message}", flush=True)
    try:
        input("   Press Enter to run this call... ")
    except EOFError:
        # A piped or otherwise non-interactive terminal should still complete.
        print("\n   Input unavailable; continuing.", flush=True)


def _show_result(result: ScenarioResult) -> None:
    if result.outcome.allowed:
        actual = "ALLOW"
    elif result.outcome.denied:
        actual = "DENY"
    else:
        actual = "ERROR"
    mark = "PASS" if actual == result.expected else "FAIL"
    detail = result.outcome.text if result.outcome.allowed else result.outcome.error
    if detail and "Proof-of-Possession verification failed" in detail:
        detail = "Proof-of-Possession verification failed"
    print(
        f"   [{mark}] expected={result.expected} actual={actual}",
        flush=True,
    )
    if detail:
        print(f"   RESULT {detail}", flush=True)


async def run_baseline(
    *,
    show: bool = True,
    step: bool = False,
) -> list[ScenarioResult]:
    """Establish tool-level task scope before introducing delegation."""
    authority = create_authority()
    state_dir = tempfile.TemporaryDirectory(prefix="tenuo-tool-scope-demo-")
    state_path = Path(state_dir.name) / "operations.sqlite3"

    try:
        if show:
            print("\nTool-level task scope over MCP", flush=True)
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=state_path,
        ) as mcp:
            if show:
                _show_case(1, "read checkout metrics")
                if step:
                    _pause_for_stage(
                        "The warrant permits this tool with service=checkout."
                    )
            allowed = await mcp.call(
                authority.orchestrator,
                "read_metrics",
                {"service": "checkout"},
            )
            allowed_result = ScenarioResult("read checkout metrics", "ALLOW", allowed)
            if show:
                _show_result(allowed_result)

            if show:
                _show_case(2, "read payments metrics")
                if step:
                    _pause_for_stage(
                        "The tool is unchanged; only the service argument is outside scope."
                    )
            denied = await mcp.call(
                authority.orchestrator,
                "read_metrics",
                {"service": "payments"},
            )
            denied_result = ScenarioResult("read payments metrics", "DENY", denied)
            if show:
                _show_result(denied_result)
    finally:
        state_dir.cleanup()

    return [allowed_result, denied_result]


async def run_cases(
    *,
    show: bool = True,
    step: bool = False,
) -> list[ScenarioResult]:
    authority = create_authority()
    state_dir = tempfile.TemporaryDirectory(prefix="tenuo-incident-demo-")
    state_path = Path(state_dir.name) / "operations.sqlite3"
    results: list[ScenarioResult] = []

    async def run_case(
        index: int,
        name: str,
        expected: str,
        mcp: OperationsMCP,
        presented: PresentedAuthority,
        tool: str,
        arguments: dict[str, object],
        watch: str,
    ) -> ToolOutcome:
        if show:
            _show_case(index, name)
            if step:
                _pause_for_stage(watch)
        outcome = await mcp.call(presented, tool, arguments)
        result = ScenarioResult(name, expected, outcome)
        results.append(result)
        if show:
            _show_result(result)
        return outcome

    try:
        if show:
            print("\nTask-scoped authorization over MCP", flush=True)
        async with OperationsMCP(
            issuer_public_hex=authority.issuer_public_hex,
            state_path=state_path,
        ) as mcp:
            await run_case(
                1,
                "parent reads payments deployment",
                "ALLOW",
                mcp,
                authority.orchestrator,
                "read_deployment",
                {"service": "payments"},
                "The parent warrant permits deployment reads for checkout and payments.",
            )

            await run_case(
                2,
                "delegated read",
                "ALLOW",
                mcp,
                authority.delegated_worker,
                "read_deployment",
                {"service": "checkout"},
                "The child warrant permits this exact read.",
            )

            await run_case(
                3,
                "read outside service scope",
                "DENY",
                mcp,
                authority.delegated_worker,
                "read_deployment",
                {"service": "payments"},
                "The tool is still permitted, but service=payments is outside the task.",
            )

            await run_case(
                4,
                "worker rollback",
                "DENY",
                mcp,
                authority.delegated_worker,
                "rollback_deployment",
                {"service": "checkout", "deployment": "8c1e"},
                "The parent permits rollback, but the worker's child warrant does not.",
            )

            stolen_authority = PresentedAuthority(
                authority.delegated_worker.chain,
                SigningKey.generate(),
            )
            await run_case(
                5,
                "stolen chain",
                "DENY",
                mcp,
                stolen_authority,
                "read_deployment",
                {"service": "checkout"},
                "The chain is valid, but the caller cannot prove it is the named holder.",
            )

            await run_case(
                6,
                "child without parent",
                "DENY",
                mcp,
                authority.delegated_worker.detached(),
                "read_deployment",
                {"service": "checkout"},
                "The child is valid only with its verifiable parent lineage.",
            )

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
            await run_case(
                7,
                "expired child",
                "DENY",
                mcp,
                expired_authority,
                "read_deployment",
                {"service": "checkout"},
                "The operation is in scope, but the task authority has expired.",
            )

            if show:
                print("\nVERIFY protected state was not changed", flush=True)
                if step:
                    _pause_for_stage(
                        "The rollback handler should never have changed deployment state."
                    )
            state = await mcp.call(
                authority.delegated_worker,
                "read_deployment",
                {"service": "checkout"},
            )
            if not state.allowed:
                raise AssertionError(f"protected-state read failed: {state.error}")
            snapshot = json.loads(state.text)
            if snapshot["deployment"] != "8c1e" or snapshot["rollbacks_executed"] != 0:
                raise AssertionError("denied rollback changed operations state")
    finally:
        state_dir.cleanup()

    if show:
        print("[PASS] deployment=8c1e, rollbacks_executed=0", flush=True)

    return results
