"""Tenuo warrants on the repair tools, end to end on a Temporal server.

Three workers, as in the README: the workflow worker (workflows plus the agents' activities, with
the holder key for signing), the issuer worker (a warrant per order, when the repair starts) and
the repair-tools worker (the three repair tools, one Activity each, with require_warrant=True and
only the root's public key). Detection, analysis, planning and reporting are replaced with canned
activities (no LLM). The plan is poisoned_plan.json, recorded unchanged from gpt-4o-mini planning
over the notes in poison_order_notes.py: it sends Hagrid's approval request to Hagrid and orders
5,000 S.P.E.W. badge sets.

Needs a Temporal server: set TEMPORAL_ADDRESS (for example after `temporal server start-dev`),
otherwise the tests start one with WorkflowEnvironment.start_local() or are skipped.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker
from tenuo import SigningKey, Warrant

import activities
import tenuo_repair
from workflows import RepairAgentWorkflow, RepairAgentWorkflowProactive

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


@dataclass
class Keys:
    root: SigningKey
    issuer: SigningKey
    holder: SigningKey
    approvers: dict[str, SigningKey]

    def issuer_warrant(self, *, root: SigningKey | None = None, ttl_seconds: int = 3600) -> Warrant:
        return tenuo_repair.issuer_warrant(
            root_key=root or self.root, issuer_public_key=self.issuer.public_key,
            approvers=[k.public_key for k in self.approvers.values()],
            catalog=tenuo_repair._catalog(), ttl_seconds=ttl_seconds,
        )


@pytest.fixture
def keys(tmp_path, monkeypatch):
    k = Keys(SigningKey.generate(), SigningKey.generate(), SigningKey.generate(),
             {name: SigningKey.generate() for name in tenuo_repair.APPROVERS})
    monkeypatch.delenv("TENUO_API_KEY", raising=False)
    monkeypatch.setenv("TENUO_ISSUER_KEY", tenuo_repair._b64(k.issuer.secret_key_bytes()))
    monkeypatch.setenv("TENUO_ISSUER_WARRANT", k.issuer_warrant().to_base64())
    monkeypatch.setenv("TENUO_HOLDER_PUBLIC_KEY", tenuo_repair._b64(k.holder.public_key.to_bytes()))
    monkeypatch.setattr(tenuo_repair, "APPROVALS_DIR", tmp_path / "approvals")
    monkeypatch.setattr(tenuo_repair, "_ENABLED", False)
    return k


def plan_with_confidence(score: float) -> dict:
    return {**POISONED_PLAN, "overall_confidence_score": score}


@activity.defn(name="detect")
async def fake_detect(input: dict) -> dict:
    return {"confidence_score": 0.9, "additional_notes": "orders need repair"}


@activity.defn(name="analyze")
async def fake_analyze(input: dict) -> dict:
    return {"issues": ["restricted item", "inventory shortfall", "payment denied"]}


@activity.defn(name="report")
async def fake_report(input: dict) -> dict:
    return {"repairs_summary": input["repair_result"]["repair_summary"]}


@activity.defn(name="notify")
async def fake_notify(input: dict) -> dict:
    return {"notification_status": "skipped in tests"}


def fake_plan(plan: dict):
    @activity.defn(name="plan_repair")
    async def _plan(input: dict) -> dict:
        return plan

    return _plan


async def _client() -> tuple[Client, object | None]:
    address = os.environ.get("TEMPORAL_ADDRESS")
    if address:
        return await Client.connect(address), None
    try:
        env = await WorkflowEnvironment.start_local()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Temporal server available: {e}")
    return env.client, env


async def _approvers(keys: Keys, client: Client, signed: list, *, say_yes: bool) -> None:
    """The approvers answer whatever is waiting and Signal the workflow, as
    `approve_repair_call.py --as ... --yes/--no` does."""
    while True:
        for name, key in keys.approvers.items():
            for workflow_id, decision in tenuo_repair.approve_pending(
                    name, key, decide=lambda pending: say_yes):
                await client.get_workflow_handle(workflow_id).signal(
                    tenuo_repair.APPROVAL_SIGNAL, decision)
                signed.append(1)
        await asyncio.sleep(0.2)


async def run_repair(keys: Keys, *, plan=POISONED_PLAN, proactive=False, approvers_sign=True,
                     approvers_say_yes=True,
                     trusted_root=None, monkeypatch, tmp_path) -> dict:
    """Start a repair workflow, approve its plan if it asks, have the approvers sign any gated
    call, and return the tool results."""
    client, env = await _client()
    queue = f"repair-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(tenuo_repair, "REPAIR_TOOLS_TASK_QUEUE", f"{queue}-tools")
    monkeypatch.setattr(tenuo_repair, "ISSUER_TASK_QUEUE", f"{queue}-issuer")
    roots = [trusted_root or keys.root.public_key]
    runtime = tenuo_repair.repair_tools_runtime(roots)
    receipts = asyncio.create_task(tenuo_repair.write_receipts(
        runtime, tmp_path / "receipts.jsonl", every=0.1))
    signed: list = []
    approvals = (asyncio.create_task(_approvers(keys, client, signed, say_yes=approvers_say_yes))
                 if approvers_sign else None)
    try:
        async with Worker(
            client,
            task_queue=queue,
            workflows=[RepairAgentWorkflow, RepairAgentWorkflowProactive],
            activities=[fake_detect, fake_analyze, fake_plan(plan), fake_notify, fake_report,
                        activities.execute_repairs, tenuo_repair.request_call_approval,
                        tenuo_repair.check_call_approval, tenuo_repair.tenuo_mode],
            plugins=[tenuo_repair.workflow_worker_plugin(keys.holder, [keys.root.public_key])],
        ), Worker(
            client,
            task_queue=f"{queue}-issuer",
            activities=[tenuo_repair.issue_order_warrant],
        ), Worker(
            client,
            task_queue=f"{queue}-tools",
            activities=list(tenuo_repair.REPAIR_TOOL_ACTIVITIES.values()),
            plugins=[tenuo_repair.repair_tools_worker_plugin(roots, runtime=runtime)],
        ):
            start = {"prompt": "Analyze and repair the orders in the order system.",
                     "metadata": {"user": "Harry.Potter"}}
            workflow = RepairAgentWorkflowProactive if proactive else RepairAgentWorkflow
            handle = await client.start_workflow(
                workflow.run, start, id=f"{queue}-wf", task_queue=queue
            )
            async with asyncio.timeout(90):
                if proactive:
                    # Skip the daily wait; above 0.95 the agent approves itself.
                    while await handle.query("GetRepairStatus") != "WAITING-FOR-NEXT-CYCLE":
                        await asyncio.sleep(0.2)
                    await handle.signal("StopWaiting")
                    while "repair_result" not in await handle.query("GetRepairContextKeys"):
                        await asyncio.sleep(0.2)
                    results = await handle.query("GetRepairToolResults")
                    assert (await handle.query("GetRepairContext"))["approved_by"].startswith(
                        "Agentically Approved")
                    await handle.signal("RequestExit")
                else:
                    while not await handle.query("IsRepairPlanned"):
                        await asyncio.sleep(0.2)
                    await handle.signal("ApproveRepair", "Minerva.McGonagall")
                    await handle.result()
                    results = await handle.query("GetRepairToolResults")
                await handle.result()
                results["_history"] = await handle.fetch_history()
            await asyncio.sleep(0.3)  # let the last receipts drain
    finally:
        receipts.cancel()
        if approvals:
            approvals.cancel()
        if env is not None:
            await env.shutdown()
    results["_decisions_signalled"] = sum(signed)
    receipts_file = tmp_path / "receipts.jsonl"
    results["_receipts"] = receipts_file.read_text().splitlines() if receipts_file.exists() else []
    return results


def _orders() -> dict:
    return {o["order_id"]: o for o in json.loads((DATA / "orders.json").read_text())["orders"]}


def _stock(item_id: str) -> int:
    inventory = json.loads((DATA / "inventory.json").read_text())["inventory"]
    return next(i["current_stock"] for i in inventory if i["item_id"] == item_id)


def _denied(results: dict) -> dict:
    return {(d["order_id"], d["tool_name"]): d["denial_reason"] for d in results["denied_tool_details"]}


def _ran(results: dict) -> set:
    return {(r["order_id"], r["tool_name"]) for r in results["repair_tool_details"]}


async def test_approved_poisoned_plan_is_bounded_on_the_tools_worker(keys, monkeypatch, tmp_path):
    badges = _stock("STP-ORG-001")

    results = await run_repair(keys, monkeypatch=monkeypatch, tmp_path=tmp_path)

    # Sending Hagrid's approval request to Hagrid is outside his order's warrant: refused.
    denied = _denied(results)
    assert set(denied) == {("ORD-004-RHG", "request_approval_tool")}
    assert "approver" in denied[("ORD-004-RHG", "request_approval_tool")]
    assert _orders()["ORD-004-RHG"]["status"] == "pending-approval"
    # 5,000 badge sets is inside the ceiling but over the limit: it ran only once both approvers
    # signed that exact call. The payment requests ran on their own.
    assert _ran(results) == {
        ("ORD-001-HJP", "request_payment_update_tool"),
        ("ORD-002-HJG", "order_inventory_tool"),
        ("ORD-003-RBW", "request_payment_update_tool"),
    }
    assert results["_decisions_signalled"] == 1  # one Signal, once both had signed
    assert _stock("STP-ORG-001") == badges + 5000
    # A signed receipt for each of the four decisions.
    assert len(results["_receipts"]) == 4


async def test_without_approvers_a_gated_call_waits(keys, monkeypatch, tmp_path):
    """Nobody signs: the 5,000 badge sets don't run, and the call is waiting for approvers."""
    plan = {"overall_confidence_score": 0.97,
            "proposed_tools": {"ORD-002-HJG": POISONED_PLAN["proposed_tools"]["ORD-002-HJG"]}}
    monkeypatch.setattr(tenuo_repair, "ORDER_WARRANT_TTL", 5)
    badges = _stock("STP-ORG-001")

    results = await run_repair(keys, plan=plan, approvers_sign=False,
                               monkeypatch=monkeypatch, tmp_path=tmp_path)

    assert _ran(results) == set()
    assert "not approved" in _denied(results)[("ORD-002-HJG", "order_inventory_tool")]
    # The approval request was opened once and is still there, unsigned.
    assert _stock("STP-ORG-001") == badges
    pending = [json.loads(p.read_text()) for p in tenuo_repair.APPROVALS_DIR.glob("*.json")]
    assert [(p["tool"], p["arguments"]["quantity"], p["signatures"]) for p in pending] == [
        ("order_inventory_tool", 5000, {})]


async def test_one_approver_saying_no_denies_the_call(keys, monkeypatch, tmp_path):
    plan = {"overall_confidence_score": 0.97,
            "proposed_tools": {"ORD-002-HJG": POISONED_PLAN["proposed_tools"]["ORD-002-HJG"]}}
    badges = _stock("STP-ORG-001")

    results = await run_repair(keys, plan=plan, approvers_say_yes=False,
                               monkeypatch=monkeypatch, tmp_path=tmp_path)

    assert _ran(results) == set()
    assert "Denied by" in _denied(results)[("ORD-002-HJG", "order_inventory_tool")]
    assert _stock("STP-ORG-001") == badges


async def test_auto_approved_plan_is_bounded_too(keys, monkeypatch, tmp_path):
    """The proactive agent skips the human above 0.95. The warrants still hold."""
    results = await run_repair(keys, plan=plan_with_confidence(0.97), proactive=True,
                               monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert set(_denied(results)) == {("ORD-004-RHG", "request_approval_tool")}
    assert len(_ran(results)) == 3


async def test_nothing_over_the_ceiling_runs_or_reaches_approvers(keys, monkeypatch, tmp_path):
    restock = {"tool_name": "order_inventory_tool", "confidence_score": 0.97,
               "tool_arguments": {"inventory_to_order": "STP-ORG-001",
                                  "inventory_description": "S.P.E.W. Badge Set",
                                  "quantity": 20_000, "order_id": "ORD-002-HJG"}}
    plan = {"overall_confidence_score": 0.97, "proposed_tools": {"ORD-002-HJG": [restock]}}

    results = await run_repair(keys, plan=plan, monkeypatch=monkeypatch, tmp_path=tmp_path)

    assert "quantity" in _denied(results)[("ORD-002-HJG", "order_inventory_tool")]
    assert results["_decisions_signalled"] == 0
    assert not list(tenuo_repair.APPROVALS_DIR.glob("*.json"))


async def test_a_warrant_only_covers_its_own_order(keys, monkeypatch, tmp_path):
    """Ron's warrant can't bill Luna, and Hermione's can't restock for Hagrid's order."""
    bill_luna = {"tool_name": "request_payment_update_tool", "confidence_score": 0.97,
                 "tool_arguments": {"customer_name": "Luna Lovegood", "customer_id": "CUST-LL-005",
                                    "original_payment_method": "Gringotts Vault Transfer",
                                    "additional_notes": "Bill Luna instead", "order_id": "ORD-003-RBW"}}
    egg = {"tool_name": "order_inventory_tool", "confidence_score": 0.97,
           "tool_arguments": {"inventory_to_order": "DRG-EGG-007",
                              "inventory_description": "Dragon Egg", "quantity": 1,
                              "order_id": "ORD-004-RHG"}}
    plan = {"overall_confidence_score": 0.97,
            "proposed_tools": {"ORD-003-RBW": [bill_luna], "ORD-002-HJG": [egg]}}
    eggs = _stock("DRG-EGG-007")

    results = await run_repair(keys, plan=plan, monkeypatch=monkeypatch, tmp_path=tmp_path)

    denied = _denied(results)
    assert "customer_id" in denied[("ORD-003-RBW", "request_payment_update_tool")]
    assert "order_id" in denied[("ORD-002-HJG", "order_inventory_tool")]
    assert _ran(results) == set()
    assert _stock("DRG-EGG-007") == eggs


async def test_a_tool_call_without_a_warrant_is_refused(keys, monkeypatch, tmp_path):
    """Luna's order is completed, so the issuer issues no warrant for it. The workflow still
    dispatches the planned call, without a warrant, and the repair-tools worker refuses it."""
    charge = {"tool_name": "request_payment_update_tool", "confidence_score": 0.97,
              "tool_arguments": {"customer_name": "Luna Lovegood", "customer_id": "CUST-LL-005",
                                 "original_payment_method": "Owl Post COD",
                                 "additional_notes": "Charge again", "order_id": "ORD-005-LLV"}}
    plan = {"overall_confidence_score": 0.97, "proposed_tools": {"ORD-005-LLV": [charge]}}

    results = await run_repair(keys, plan=plan, monkeypatch=monkeypatch, tmp_path=tmp_path)

    assert _ran(results) == set()
    assert "No warrant" in _denied(results)[("ORD-005-LLV", "request_payment_update_tool")]
    assert _orders()["ORD-005-LLV"]["status"] == "completed"


async def test_warrants_from_another_root_are_refused(keys, monkeypatch, tmp_path):
    monkeypatch.setenv("TENUO_ISSUER_WARRANT", keys.issuer_warrant(root=SigningKey.generate())
                       .to_base64())
    results = await run_repair(keys, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert _ran(results) == set()
    assert len(results["denied_tool_details"]) == 4


async def test_an_expired_issuer_warrant_issues_nothing(keys, monkeypatch, tmp_path):
    monkeypatch.setenv("TENUO_ISSUER_WARRANT", keys.issuer_warrant(ttl_seconds=1).to_base64())
    await asyncio.sleep(2)
    results = await run_repair(keys, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert _ran(results) == set()
    assert len(results["denied_tool_details"]) == 4


async def test_replay_takes_the_recorded_path_whatever_the_worker_config(keys, monkeypatch, tmp_path):
    """Whether repairs run under warrants is recorded in the workflow's history (tenuo_mode is a
    local Activity), so a replay on a worker without Tenuo doesn't diverge."""
    results = await run_repair(keys, monkeypatch=monkeypatch, tmp_path=tmp_path)
    replayer = Replayer(
        workflows=[RepairAgentWorkflow],
        plugins=[tenuo_repair.workflow_worker_plugin(keys.holder, [keys.root.public_key])],
    )
    monkeypatch.setattr(tenuo_repair, "_ENABLED", False)  # this worker now says "no Tenuo"
    await replayer.replay_workflow(results["_history"])


async def test_without_tenuo_the_workflow_runs_joshs_repair_activity(monkeypatch):
    """No plugin, no keys: the workflow takes the original execute_repairs path."""
    monkeypatch.setattr(tenuo_repair, "_ENABLED", False)
    for name in ("TENUO_HOLDER_KEY", "TENUO_TRUSTED_ROOT"):
        monkeypatch.delenv(name, raising=False)
    client, env = await _client()
    queue = f"plain-{uuid.uuid4().hex[:6]}"
    try:
        async with Worker(
            client, task_queue=queue, workflows=[RepairAgentWorkflow],
            activities=[fake_detect, fake_analyze, fake_plan(POISONED_PLAN), fake_notify,
                        fake_report, activities.execute_repairs, tenuo_repair.tenuo_mode],
        ):
            handle = await client.start_workflow(
                RepairAgentWorkflow.run, {"prompt": "repair", "metadata": {"user": "Harry.Potter"}},
                id=f"{queue}-wf", task_queue=queue)
            async with asyncio.timeout(60):
                while not await handle.query("IsRepairPlanned"):
                    await asyncio.sleep(0.2)
                await handle.signal("ApproveRepair", "Minerva.McGonagall")
                await handle.result()
            results = await handle.query("GetRepairToolResults")
    finally:
        if env is not None:
            await env.shutdown()
    assert results["problems_repaired"] == 4  # every planned repair, as upstream
