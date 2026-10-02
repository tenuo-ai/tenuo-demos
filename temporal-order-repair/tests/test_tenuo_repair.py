"""Tenuo warrants for the repair agent (tenuo_repair.py): what an order's warrant allows, which
calls need approvers, how the keys are split, and that nothing changes without them.

Run with: python -m pytest tests -v
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment
from tenuo import SigningKey

import activities
import tenuo_repair

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
POISONED_PLAN = json.loads((HERE / "poisoned_plan.json").read_text())


@pytest.fixture(autouse=True)
def restore_data(tmp_path):
    """The mock tools write to data/*.json. Put them back after each test."""
    for name in ("orders.json", "inventory.json"):
        shutil.copy(DATA / name, tmp_path / name)
    yield
    for name in ("orders.json", "inventory.json"):
        shutil.copy(tmp_path / name, DATA / name)


def _order(order_id: str) -> dict:
    return tenuo_repair._load_order(order_id)


def _order_warrant(order_id: str):
    root, issuer, holder = SigningKey.generate(), SigningKey.generate(), SigningKey.generate()
    approvers = [SigningKey.generate().public_key for _ in tenuo_repair.APPROVERS]
    issuer_warrant = tenuo_repair.issuer_warrant(
        root_key=root, issuer_public_key=issuer.public_key, approvers=approvers,
        catalog=tenuo_repair._catalog(),
    )
    return tenuo_repair.order_repair_template(
        _order(order_id), issuer=issuer_warrant, issuer_key=issuer,
        holder_public_key=holder.public_key,
    )


def _restock(order_id: str, item: str, quantity: int) -> dict:
    return {"order_id": order_id, "inventory_to_order": item,
            "inventory_description": "restock", "quantity": quantity}


def _decision(warrant, tool: str, args: dict) -> str:
    return warrant.approval_requirement(tool, args).status


def test_restocks_run_alone_up_to_the_limit_then_need_approvers():
    hermione = _order_warrant("ORD-002-HJG")
    restock = lambda *a: _decision(hermione, "order_inventory_tool", _restock(*a))  # noqa: E731
    assert restock("ORD-002-HJG", "STP-ORG-001", 50) == "exempt"      # on her order, small
    assert restock("ORD-002-HJG", "STP-ORG-001", 300) == "required"   # large
    assert restock("ORD-002-HJG", "STP-ORG-001", 5000) == "required"  # the poisoned note
    assert restock("ORD-002-HJG", "DRG-EGG-007", 1) == "required"     # not on her order
    assert restock("ORD-002-HJG", "STP-ORG-001", 20_000) == "denied"  # over the hard ceiling
    assert restock("ORD-004-RHG", "STP-ORG-001", 5) == "denied"       # someone else's order


def test_every_approver_must_sign():
    hermione = _order_warrant("ORD-002-HJG")
    assert len(hermione.required_approvers()) == len(tenuo_repair.APPROVERS)
    assert hermione.approval_threshold() == len(tenuo_repair.APPROVERS)


def test_approvals_go_only_to_the_ministry():
    hagrid = _order_warrant("ORD-004-RHG")
    request = {"order_id": "ORD-004-RHG", "approval_request_contents": "Approve DRG-EGG-007"}
    assert not hagrid.check_constraints(
        "request_approval_tool", {**request, "approver": tenuo_repair.ALLOWED_APPROVER}
    )
    assert hagrid.check_constraints(
        "request_approval_tool", {**request, "approver": "hagrid@hogwarts.edu"}
    )


def test_payment_requests_go_only_to_the_orders_customer():
    ron = _order_warrant("ORD-003-RBW")
    request = {"order_id": "ORD-003-RBW", "customer_name": "Ron", "original_payment_method": "x",
               "additional_notes": "payment denied"}
    assert not ron.check_constraints(
        "request_payment_update_tool", {**request, "customer_id": "CUST-RW-003"})
    assert ron.check_constraints(
        "request_payment_update_tool", {**request, "customer_id": "CUST-LL-005"})  # bill Luna


def test_keygen_splits_the_keys(tmp_path, monkeypatch):
    for name in ("ROOT_ENV", "ISSUER_ENV", "WORKER_ENV", "TOOLS_ENV"):
        monkeypatch.setattr(tenuo_repair, name, tmp_path / getattr(tenuo_repair, name).name)
    monkeypatch.setattr(tenuo_repair, "ROOT", tmp_path)
    tenuo_repair._keygen()
    root = (tmp_path / "tenuo-root.env").read_text()
    issuer = (tmp_path / "tenuo-issuer.env").read_text()
    worker = (tmp_path / "tenuo-worker.env").read_text()
    tools = (tmp_path / "tenuo-tools.env").read_text()
    assert "TENUO_ROOT_KEY=" in root
    assert "TENUO_ISSUER_KEY=" in issuer and "TENUO_ROOT_KEY=" not in issuer
    assert "TENUO_HOLDER_KEY=" in worker and "TENUO_ISSUER_KEY=" not in worker
    # Only public keys, plus the key it signs receipts with, which grants nothing.
    assert "TENUO_TRUSTED_ROOT=" in tools
    assert [line.split("=")[0] for line in tools.splitlines() if "_KEY=" in line] == ["TENUO_RECEIPT_KEY"]
    for name in tenuo_repair.APPROVERS:
        assert "TENUO_APPROVER_KEY=" in (tmp_path / f"tenuo-approver-{name}.env").read_text()


async def test_the_issuer_reads_the_order_not_the_plan(monkeypatch):
    root, issuer, holder = SigningKey.generate(), SigningKey.generate(), SigningKey.generate()
    issuer_warrant = tenuo_repair.issuer_warrant(
        root_key=root, issuer_public_key=issuer.public_key,
        approvers=[SigningKey.generate().public_key], catalog=tenuo_repair._catalog())
    monkeypatch.delenv("TENUO_API_KEY", raising=False)
    monkeypatch.setenv("TENUO_ISSUER_KEY", tenuo_repair._b64(issuer.secret_key_bytes()))
    monkeypatch.setenv("TENUO_ISSUER_WARRANT", issuer_warrant.to_base64())
    monkeypatch.setenv("TENUO_HOLDER_PUBLIC_KEY", tenuo_repair._b64(holder.public_key.to_bytes()))
    env = ActivityEnvironment()

    chain = await env.run(tenuo_repair.issue_order_warrant, "ORD-003-RBW")
    ron = tenuo_repair.Warrant.from_base64(chain[-1])
    assert ron.depth == 1 and ron.ttl_remaining.total_seconds() <= tenuo_repair.ORDER_WARRANT_TTL
    assert await env.run(tenuo_repair.issue_order_warrant, "ORD-005-LLV") is None  # completed
    assert await env.run(tenuo_repair.issue_order_warrant, "ORD-999-XXX") is None  # unknown


async def test_without_warrants_behavior_is_unchanged(monkeypatch):
    monkeypatch.delenv("TENUO_TRUSTED_ROOT", raising=False)
    monkeypatch.delenv("TENUO_HOLDER_KEY", raising=False)
    result = await ActivityEnvironment().run(
        activities.repair_some_stuff, {"planning_result": POISONED_PLAN}
    )
    assert result["problems_repaired"] == 4  # every planned repair, poisoned or not


async def test_a_worker_with_keys_refuses_inline_repairs(monkeypatch):
    """With the worker keys, repairs only run on the repair-tools worker, one Activity each."""
    monkeypatch.setenv("TENUO_HOLDER_KEY", "set")
    with pytest.raises(ApplicationError) as e:
        await ActivityEnvironment().run(
            activities.repair_some_stuff, {"planning_result": POISONED_PLAN}
        )
    assert e.value.non_retryable


def test_a_cloud_decision_becomes_a_signal_payload():
    base = {"metadata": {"workflow_id": "wf-1"}, "request_hash": "q80="}
    assert tenuo_repair.decision_from_cloud_request({**base, "status": "pending"}) is None
    approved = tenuo_repair.decision_from_cloud_request(
        {**base, "status": "approved", "responses": [{"signed_approval": "c2ln"}]})
    assert approved == {"request": "abcd", "approvals": ["c2ln"]}
    denied = tenuo_repair.decision_from_cloud_request({**base, "status": "denied"})
    assert denied["request"] == "abcd" and denied["denied"].startswith("Denied in Tenuo Cloud")


def test_the_webhook_receiver_only_accepts_signed_fresh_events(monkeypatch):
    import hashlib
    import hmac
    import time

    monkeypatch.setattr("sys.argv", ["run_approval_webhook.py"])
    import run_approval_webhook as hook

    body, secret, now = b'{"type": "approval.approved"}', "s3cret", str(int(time.time()))
    good = hmac.new(secret.encode(), f"{now}.".encode() + body, hashlib.sha256).hexdigest()
    assert hook.verify(body, good, now, secret)
    assert not hook.verify(body, good, now, "other-secret")
    assert not hook.verify(body + b" ", good, now, secret)
    stale = str(int(time.time()) - 3600)
    old = hmac.new(secret.encode(), f"{stale}.".encode() + body, hashlib.sha256).hexdigest()
    assert not hook.verify(body, old, stale, secret)
    # What Cloud sends today: the body alone, as "sha256=<hex>", with no timestamp header.
    body_only = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert hook.verify(body, body_only, "", secret)
    assert not hook.verify(body, body_only, "", "other-secret")
    assert not hook.verify(body, "", "", secret)
