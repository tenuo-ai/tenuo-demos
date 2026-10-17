"""Trusted task controller. Issuer secrets stay in this process, outside history."""

import argparse
import asyncio
import json
import logging
import uuid

from lifecycle_workflow import LifecycleWorkflow
from policy import task_warrant
from run_demo import scripted_policy
from tenuo import SigningKey
from tenuo.temporal import tenuo_headers
from tools import Shop
from worker import make_worker

from temporalio.claude_agent_sdk.testing import ScriptedClaude
from temporalio.client import Client


async def wait_phase(handle, phase):
    async def poll():
        while True:
            status = await handle.query(LifecycleWorkflow.status)
            if status["phase"] == phase:
                return status
            await asyncio.sleep(0.05)

    return await asyncio.wait_for(poll(), 90)


async def run(address="localhost:7233", *, restart=False, runner_factory=None):
    client = await Client.connect(address)
    issuer, holder = SigningKey.generate(), SigningKey.generate()
    wid = "lifecycle-" + uuid.uuid4().hex
    order_id = "order-123"
    initial = task_warrant(issuer, holder, workflow_id=wid, order_id=order_id)
    shop, decisions = Shop(), []

    def audit(event):
        decisions.append(event)
        print(f"[tenuo] {event.tool}: {event.decision} {event.arguments}", flush=True)

    def create_worker():
        runner = (
            runner_factory(shop)
            if runner_factory
            else ScriptedClaude(scripted_policy, engine_tools=shop.engine_tools())
        )
        return make_worker(
            client,
            wid,
            runner,
            issuer,
            holder,
            lifecycle=True,
            audit_callback=audit,
            redact_args_in_logs=False,
        )

    worker, plugin = create_worker()
    authorized = Client(client.service_client, interceptors=[plugin.client_interceptor])
    plugin.client_interceptor.set_headers_for_workflow(
        wid, tenuo_headers(initial, "task")
    )
    print(
        f"[controller] issued {initial.id}: refund <= 100 for {order_id}; TTL 600s",
        flush=True,
    )
    async with worker:
        handle = await authorized.start_workflow(
            LifecycleWorkflow.run,
            order_id,
            id=wid,
            task_queue=wid,
        )
        before = await wait_phase(handle, "awaiting approval")
        assert len(before["calls"]) == 3
        assert shop.refunds == [{"order_id": order_id, "amount": 25}]
        denied = [event for event in decisions if event.decision == "DENY"]
        assert [(event.tool, event.arguments) for event in denied] == [
            ("issue_refund", {"order_id": order_id, "amount": 250}),
        ]
        print(
            "[workflow] denied 250 without invoking refund; awaiting approval",
            flush=True,
        )
        await handle.execute_update(LifecycleWorkflow.approve_refund, True)
        print("[human] approval recorded by Temporal Update", flush=True)
        waiting = await wait_phase(handle, "awaiting authority")
        assert len(waiting["calls"]) == 4
        assert shop.refunds == [{"order_id": order_id, "amount": 25}]
        assert len([event for event in decisions if event.decision == "DENY"]) == 2
        print(
            "[controller] approval alone still denied 250; issuing new warrant",
            flush=True,
        )
        replacement = task_warrant(
            issuer,
            holder,
            workflow_id=wid,
            order_id=order_id,
            limit=250,
        )
        await handle.execute_update(
            LifecycleWorkflow.install_authority,
            tenuo_headers(replacement, "task"),
        )
        await wait_phase(handle, "authority installed")
        print(
            f"[controller] installed {replacement.id}: refund <= 250 for {order_id}; TTL 600s",
            flush=True,
        )
        if not restart:
            await handle.execute_update(LifecycleWorkflow.retry_refund)
            result = await asyncio.wait_for(handle.result(), 90)
    if restart:
        # A new Worker has no Workflow cache. It must reconstruct approval and
        # replacement authority from history before accepting the retry Update.
        worker, _ = create_worker()
        async with worker:
            await handle.execute_update(LifecycleWorkflow.retry_refund)
            result = await asyncio.wait_for(handle.result(), 90)
    assert shop.refunds == [
        {"order_id": order_id, "amount": 25},
        {"order_id": order_id, "amount": 250},
    ]
    assert len(shop.invocations) == 3
    print(f"[workflow] complete: {json.dumps(shop.refunds)}", flush=True)
    return (
        result,
        shop,
        decisions,
        initial,
        replacement,
        await handle.fetch_history(),
        issuer,
        holder,
    )


if __name__ == "__main__":
    # Tests keep full SDK logs; the standalone trace shows audit decisions
    # without expected denial warning tracebacks obscuring the sequence.
    logging.basicConfig(level=logging.ERROR)
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--restart", action="store_true")
    opts = parser.parse_args()
    asyncio.run(run(opts.address, restart=opts.restart))
