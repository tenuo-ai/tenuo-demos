"""Authority changes require a trusted new signature, even after approval."""

import asyncio
import base64
import os
import time

import pytest
from policy import task_warrant
from run_lifecycle import run
from tenuo.temporal import tenuo_headers
from tenuo.temporal._headers import _extract_warrant_from_headers
from test_boundary import Boundary, step

from temporalio.api.common.v1 import Payload
from temporalio.exceptions import ApplicationError

pytestmark = pytest.mark.asyncio
REFUND_250 = step("issue_refund", order_id="order-123", amount=250)


def warrant_in(headers):
    return _extract_warrant_from_headers({k: v.data for k, v in headers.items()})


async def test_scope_signs_with_its_authority_and_then_restores_the_start_warrant():
    b = Boundary()
    replacement = task_warrant(b.issuer, b.holder, limit=250)
    inside = b.sign(REFUND_250, authority=tenuo_headers(replacement, "task"))
    assert warrant_in(inside).id == replacement.id
    assert warrant_in(b.sign(REFUND_250)).id == b.warrant.id


async def test_controller_replacement_required_and_old_authority_unchanged():
    b = Boundary()
    # A human decision is Workflow state, not a cryptographic capability: the
    # start warrant denies 250 before and after approval.
    for _approved in (False, True):
        with pytest.raises(ApplicationError) as error:
            await b.invoke(REFUND_250)
        assert error.value.type == "constraint_violation"
    assert b.shop.refunds == []
    replacement = task_warrant(b.issuer, b.holder, limit=250)
    assert replacement.id != b.warrant.id
    headers = b.sign(REFUND_250, authority=tenuo_headers(replacement, "task"))
    await b.invoke(REFUND_250, headers)
    assert b.shop.refunds == [{"order_id": "order-123", "amount": 250}]
    with pytest.raises(ApplicationError):
        await b.invoke(REFUND_250)
    assert b.body_calls == 1


async def test_holder_cannot_issue_its_own_expanded_authority():
    b = Boundary()
    forged = task_warrant(b.holder, b.holder, limit=250)
    headers = b.sign(REFUND_250, authority=tenuo_headers(forged, "task"))
    with pytest.raises(ApplicationError):
        await b.invoke(REFUND_250, headers)
    assert b.body_calls == 0 and b.shop.refunds == []


async def test_replacement_is_bound_to_its_resource():
    b = Boundary()
    replacement = task_warrant(b.issuer, b.holder, limit=250)
    other = step("issue_refund", order_id="order-456", amount=250)
    headers = b.sign(other, authority=tenuo_headers(replacement, "task"))
    with pytest.raises(ApplicationError):
        await b.invoke(other, headers)
    assert b.body_calls == 0 and b.shop.refunds == []


async def test_expired_authority_is_denied_at_the_activity():
    b = Boundary()
    short = task_warrant(b.issuer, b.holder, ttl=1)
    await asyncio.sleep(2)
    assert short.is_expired()
    request = step("get_order", order_id="order-123")
    headers = b.sign(request, authority=tenuo_headers(short, "task"))
    with pytest.raises(ApplicationError):
        await b.invoke(request, headers)
    assert b.body_calls == 0


async def test_a_stale_schedule_time_proof_is_denied_on_its_first_attempt():
    b = Boundary()
    request = step("get_order", order_id="order-123")
    headers = b.sign(request)
    # The real verifier and clock, with the plugin's default proof windows.
    old = b.warrant.sign(
        b.holder, "get_order", request.call.input, int(time.time()) - 300
    )
    headers["x-tenuo-pop"] = Payload(data=base64.b64encode(bytes(old)))
    with pytest.raises(ApplicationError):
        await b.invoke(request, headers)
    assert b.body_calls == 0


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
