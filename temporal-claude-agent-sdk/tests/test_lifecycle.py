"""Authority changes require a trusted new signature, even after approval."""

import asyncio
import base64
import os
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from execution_proof import ExecutionProof
from policy import TOOL_ACTIVITY, task_warrant
from run_lifecycle import run
from tenuo.temporal import tenuo_headers
from test_boundary import Boundary, step

from temporalio.api.common.v1 import Payload
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment
from temporalio.worker import ExecuteActivityInput

pytestmark = pytest.mark.asyncio
TASK = "support-task-123"


async def execute(
    boundary, warrant, request, *, task=TASK, attempt=1, caller_proof=None
):
    async def dispatch(inp):
        boundary.body_calls += 1
        return await inp.fn(*inp.args)

    env = ActivityEnvironment()
    env.info = replace(
        env.info, activity_type=TOOL_ACTIVITY, workflow_id=task, attempt=attempt
    )
    inbound = ExecutionProof(
        SimpleNamespace(execute_activity=dispatch), boundary.config, "0.3.2"
    )
    inp = ExecuteActivityInput(
        fn=boundary.body,
        args=[request],
        executor=None,
        headers={k: Payload(data=v) for k, v in tenuo_headers(warrant, "task").items()},
    )
    if caller_proof is not None:
        inp.headers["x-tenuo-pop"] = Payload(data=caller_proof)
    return await env.run(inbound.execute_activity, inp)


async def test_controller_replacement_required_and_old_authority_unchanged():
    b = Boundary()
    initial = task_warrant(b.issuer, b.holder, workflow_id=TASK)
    request = step("issue_refund", order_id="order-123", amount=250)
    # A human decision is Workflow state, not a cryptographic capability.
    for approved in (False, True):
        with pytest.raises(ApplicationError) as error:
            await execute(b, initial, request)
        assert error.value.type == "constraint_violation"
        assert b.shop.refunds == []
    replacement = task_warrant(b.issuer, b.holder, workflow_id=TASK, limit=250)
    assert replacement.id != initial.id
    await execute(b, replacement, request)
    assert b.shop.refunds == [{"order_id": "order-123", "amount": 250}]
    with pytest.raises(ApplicationError):
        await execute(b, initial, request)
    assert b.body_calls == 1


async def test_execution_identity_does_not_launder_a_caller_proof():
    b = Boundary()
    warrant = task_warrant(b.issuer, b.holder, workflow_id=TASK)
    with pytest.raises(ApplicationError, match="does not accept caller proofs"):
        await execute(
            b, warrant, step("get_order", order_id="order-123"), caller_proof=b"invalid"
        )
    assert b.body_calls == 0


async def test_execution_time_retry_still_checks_current_recorded_authority():
    b = Boundary()
    warrant = task_warrant(b.issuer, b.holder, workflow_id=TASK)
    for attempt in (1, 2):
        with pytest.raises(ApplicationError) as error:
            await execute(
                b,
                warrant,
                step("issue_refund", order_id="order-123", amount=250),
                attempt=attempt,
            )
        assert error.value.non_retryable and error.value.type == "constraint_violation"
    assert b.body_calls == 0 and b.shop.refunds == []


async def test_holder_cannot_issue_its_own_expanded_authority():
    b = Boundary()
    forged = task_warrant(b.holder, b.holder, workflow_id=TASK, limit=250)
    with pytest.raises(ApplicationError):
        await execute(b, forged, step("issue_refund", order_id="order-123", amount=250))
    assert b.body_calls == 0 and b.shop.refunds == []


@pytest.mark.parametrize(
    "task,order", [("other-task", "order-123"), (TASK, "order-456")]
)
async def test_replacement_is_bound_to_task_and_resource(task, order):
    b = Boundary()
    warrant = task_warrant(b.issuer, b.holder, workflow_id=TASK, limit=250)
    with pytest.raises(ApplicationError):
        await execute(
            b, warrant, step("issue_refund", order_id=order, amount=250), task=task
        )
    assert b.body_calls == 0 and b.shop.refunds == []


async def test_expired_task_authority_cannot_get_a_fresh_execution_proof():
    b = Boundary()
    warrant = task_warrant(b.issuer, b.holder, workflow_id=TASK, ttl=1)
    await asyncio.sleep(2)
    assert warrant.is_expired()
    with pytest.raises(ApplicationError, match="expired"):
        await execute(b, warrant, step("get_order", order_id="order-123"))
    assert b.body_calls == 0


async def test_stale_schedule_proof_fails_but_worker_origin_proof_is_fresh():
    b = Boundary()
    request = step("get_order", order_id="order-123")
    headers = b.sign(request)
    # Actual core verifier against the real clock; no widened proof window.
    old = b.warrant.sign(
        b.holder, "get_order", request.call.input, int(time.time()) - 300
    )
    headers["x-tenuo-pop"] = Payload(data=base64.b64encode(bytes(old)))
    with pytest.raises(ApplicationError):
        await b.invoke(request, headers)
    assert b.body_calls == 0
    current = task_warrant(b.issuer, b.holder, workflow_id=TASK)
    await execute(b, current, request)
    assert b.body_calls == 1


@pytest.mark.skipif(
    not os.environ.get("TEMPORAL_ADDRESS"), reason="requires real Worker"
)
async def test_lifecycle_approval_replacement_and_worker_restart():
    result, shop, audit, old, new, history, issuer, holder = await run(
        os.environ["TEMPORAL_ADDRESS"],
        restart=True,
    )
    assert result["phase"] == "complete" and len(result["calls"]) == 5
    refund_events = [e for e in audit if e.tool == "issue_refund"]
    assert [e.decision for e in refund_events] == ["ALLOW", "DENY", "DENY", "ALLOW"]
    assert refund_events[-1].warrant_id == new.id
    assert all(e.warrant_id == old.id for e in refund_events[:-1])
    assert len(shop.refunds) == 2
    # Inspect serialized protobuf history, including all inputs/headers/results.
    wire = b"".join(e.SerializeToString() for e in history.events)
    for key in (issuer, holder):
        secret = bytes(key.secret_key_bytes())
        assert secret not in wire
        assert base64.b64encode(secret) not in wire
        assert secret.hex().encode() not in wire
