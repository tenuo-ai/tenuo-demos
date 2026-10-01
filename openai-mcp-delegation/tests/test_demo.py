from __future__ import annotations

import pytest

from incident_demo.scenarios import run_baseline, run_cases


@pytest.mark.asyncio
async def test_tool_level_task_scope() -> None:
    results = await run_baseline(show=False)
    actual = ["ALLOW" if result.outcome.allowed else "DENY" for result in results]
    assert actual == ["ALLOW", "DENY"]


@pytest.mark.asyncio
async def test_four_mcp_authorization_cases() -> None:
    results = await run_cases(show=False)
    actual = ["ALLOW" if result.outcome.allowed else "DENY" for result in results]
    assert actual == ["ALLOW", "DENY", "DENY", "DENY"]
