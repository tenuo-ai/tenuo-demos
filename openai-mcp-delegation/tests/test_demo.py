from __future__ import annotations

import pytest

from incident_demo.scenarios import run_baseline, run_cases, run_demo


@pytest.mark.asyncio
async def test_canonical_demo_verifies_effect_and_receipt(capsys, tmp_path) -> None:
    evidence_dir = tmp_path / "evidence"
    result = await run_demo(show=True, evidence_dir=evidence_dir)

    assert [call.outcome.status for call in result.calls] == ["allowed", "denied"]
    assert result.deployment == "8c1e"
    assert result.rollbacks_executed == 0
    assert result.receipt_decision_code
    assert (evidence_dir / "denial-receipt.txt").read_text().strip()
    assert len((evidence_dir / "enforcement-public-key.hex").read_text().strip()) == 64
    assert len((evidence_dir / "trusted-root.hex").read_text().strip()) == 64
    output = capsys.readouterr().out
    assert "DELEGATE  worker: investigate checkout only" in output
    assert "DENY      worker -> rollback_deployment(service=checkout)" in output
    assert "VERIFY    signed denial receipt valid offline" in output


@pytest.mark.asyncio
async def test_tool_level_task_scope() -> None:
    results = await run_baseline(show=False)
    actual = [result.outcome.status for result in results]
    assert actual == ["allowed", "denied"]
    assert "constraint 'service'" in (results[1].outcome.error or "").lower()


@pytest.mark.asyncio
async def test_seven_mcp_authorization_cases() -> None:
    results = await run_cases(show=False)
    actual = [result.outcome.status for result in results]
    assert actual == [
        "allowed",
        "allowed",
        "denied",
        "denied",
        "denied",
        "denied",
        "denied",
    ]
    assert '"service": "payments"' in results[0].outcome.text
    assert "constraint 'service'" in (results[2].outcome.error or "").lower()
    assert "tool 'rollback_deployment'" in (results[3].outcome.error or "").lower()
    assert "proof-of-possession" in (results[4].outcome.error or "").lower()
    assert "issuer is not trusted" in (results[5].outcome.error or "").lower()
    assert "expired" in (results[6].outcome.error or "").lower()
