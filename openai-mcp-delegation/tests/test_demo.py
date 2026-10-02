from __future__ import annotations

import pytest

from incident_demo.scenarios import run_baseline, run_cases


@pytest.mark.asyncio
async def test_tool_level_task_scope() -> None:
    results = await run_baseline(show=False)
    actual = [result.outcome.status for result in results]
    assert actual == ["allowed", "denied"]
    assert "constraint 'service'" in (results[1].outcome.error or "").lower()


@pytest.mark.asyncio
async def test_six_mcp_authorization_cases() -> None:
    results = await run_cases(show=False)
    actual = [result.outcome.status for result in results]
    assert actual == [
        "allowed",
        "denied",
        "denied",
        "denied",
        "denied",
        "denied",
    ]
    assert "constraint 'service'" in (results[1].outcome.error or "").lower()
    assert "tool 'rollback_deployment'" in (results[2].outcome.error or "").lower()
    assert "proof-of-possession" in (results[3].outcome.error or "").lower()
    assert "issuer is not trusted" in (results[4].outcome.error or "").lower()
    assert "expired" in (results[5].outcome.error or "").lower()
