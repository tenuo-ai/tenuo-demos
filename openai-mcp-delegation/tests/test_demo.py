from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from tenuo import SigningKey

from incident_demo.authority import create_authority
from incident_demo.cli import EVIDENCE_DIR
from incident_demo.mcp_client import OperationsMCP
from incident_demo.ops_server import AuthorizationAuditMiddleware
from incident_demo.scenarios import UNDELEGATED_TOOL_CODE, run_baseline, run_cases, run_demo


def _verify_cli(evidence_dir: Path, arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(Path(sys.executable).with_name("tenuo")),
            "receipt",
            "verify",
            str(evidence_dir / "denial-receipt.txt"),
            "--authorizer",
            (evidence_dir / "enforcement-public-key.hex").read_text().strip(),
            "--root",
            (evidence_dir / "trusted-root.hex").read_text().strip(),
            "--args",
            arguments,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_canonical_demo_verifies_effect_and_receipt(capsys, tmp_path) -> None:
    evidence_dir = tmp_path / "evidence"
    result = await run_demo(show=True, evidence_dir=evidence_dir)

    assert [call.outcome.status for call in result.calls] == ["allowed", "denied"]
    assert result.deployment == "8c1e"
    assert result.rollbacks_executed == 0
    assert result.receipt_decision_code == UNDELEGATED_TOOL_CODE
    assert len((evidence_dir / "enforcement-public-key.hex").read_text().strip()) == 64
    assert len((evidence_dir / "trusted-root.hex").read_text().strip()) == 64
    output = capsys.readouterr().out
    assert "DELEGATE  worker: investigate checkout only" in output
    assert (
        "DENY      worker -> rollback_deployment(service=checkout)"
        " \u2014 rollback was not delegated"
    ) in output
    assert "VERIFY    signed denial receipt valid offline" in output


@pytest.mark.asyncio
async def test_readme_verify_command_checks_the_arguments(tmp_path) -> None:
    await run_demo(show=False, evidence_dir=tmp_path)

    good = _verify_cli(tmp_path, '{"service":"checkout","deployment":"8c1e"}')
    assert good.returncode == 0, good.stdout + good.stderr
    altered = _verify_cli(tmp_path, '{"service":"checkout","deployment":"other"}')
    assert altered.returncode != 0


@pytest.mark.asyncio
async def test_denial_receipt_rejects_wrong_context(tmp_path) -> None:
    authority = create_authority()
    other_root = SigningKey.generate().public_key.to_bytes().hex()
    arguments = {"service": "checkout", "deployment": "8c1e"}
    async with OperationsMCP(
        issuer_public_hex=authority.issuer_public_hex,
        state_path=tmp_path / "state.sqlite3",
        receipt_path=tmp_path / "receipts.jsonl",
        quiet=True,
    ) as mcp:
        await mcp.call(authority.delegated_worker, "rollback_deployment", arguments)

        def verify(call_args=arguments, root=authority.issuer_public_hex, code=UNDELEGATED_TOOL_CODE):
            return mcp.verify_denial_receipt(
                "rollback_deployment",
                call_args,
                trusted_root_hex=root,
                decision_code=code,
            )

        assert verify().decision_code == UNDELEGATED_TOOL_CODE
        with pytest.raises(AssertionError):
            verify(call_args={"service": "checkout", "deployment": "other"})
        with pytest.raises(Exception):
            verify(root=other_root)
        with pytest.raises(AssertionError):
            verify(code="some-other-reason")
        (tmp_path / "receipts.enforcement-key").write_text(other_root)
        with pytest.raises(AssertionError):
            verify()


@pytest.mark.asyncio
async def test_failed_run_leaves_no_old_evidence(tmp_path, monkeypatch) -> None:
    (tmp_path / "denial-receipt.txt").write_text("from an earlier run")

    def fail(*args, **kwargs):
        raise AssertionError("verification failed")

    monkeypatch.setattr(OperationsMCP, "verify_denial_receipt", fail)
    with pytest.raises(AssertionError):
        await run_demo(show=False, evidence_dir=tmp_path)
    assert not (tmp_path / "denial-receipt.txt").exists()


@pytest.mark.asyncio
async def test_demo_step_pauses_before_each_call(monkeypatch, capsys) -> None:
    pauses = []
    monkeypatch.setattr("builtins.input", pauses.append)
    await run_demo(show=False, step=True)
    assert len(pauses) == 2


def test_evidence_dir_is_the_project_directory() -> None:
    assert EVIDENCE_DIR == Path(__file__).resolve().parents[1] / ".tenuo-demo"


class _FakeRuntime:
    def __init__(self) -> None:
        self.pending = ["receipt"]

    def drain_receipts(self) -> list[str]:
        return list(self.pending)

    def acknowledge_receipts(self, count: int) -> None:
        del self.pending[:count]


def _context() -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(name="tool"))


@pytest.mark.asyncio
async def test_receipts_are_written_when_the_tool_raises(tmp_path) -> None:
    runtime = _FakeRuntime()
    path = tmp_path / "receipts"

    async def call_next(_context):
        raise RuntimeError("tool failed")

    with pytest.raises(RuntimeError):
        await AuthorizationAuditMiddleware(runtime, path).on_call_tool(_context(), call_next)
    assert path.read_text() == "receipt\n"
    assert runtime.pending == []


@pytest.mark.asyncio
async def test_receipt_write_failure_keeps_result_and_receipt(tmp_path) -> None:
    runtime = _FakeRuntime()
    result = SimpleNamespace(structured_content=None, is_error=False)

    async def call_next(_context):
        return result

    middleware = AuthorizationAuditMiddleware(runtime, tmp_path / "missing" / "receipts")
    assert await middleware.on_call_tool(_context(), call_next) is result
    assert runtime.pending == ["receipt"]


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
