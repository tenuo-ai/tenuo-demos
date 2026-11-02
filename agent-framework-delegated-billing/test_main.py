import asyncio

import pytest
from agent_framework import Agent
from tenuo import Exact, Range, SigningKey, Warrant
from tenuo.exceptions import MonotonicityError

import main


@pytest.fixture(autouse=True)
def reset():
    main.refunds_issued.clear()
    main.invoices_read.clear()
    main.billing_runs.clear()


def run_billing(script, middleware=None, stream=False):
    agent = main.make_billing_agent("INV-4471", 4000, script + ["done"])
    if middleware is not None:
        agent = Agent(
            client=main.ScriptedChatClient(script + ["done"]),
            tools=[main.read_invoice, main.issue_refund],
            middleware=[middleware],
        )

    async def go():
        if stream:
            updates = agent.run("go", stream=True)
            async for _ in updates:
                pass
            return await updates.get_final_response()
        return await agent.run("go")

    return main.tool_calls(asyncio.run(go()))


def test_delegated_refund_runs_once_and_injected_refund_never_runs():
    asyncio.run(main.make_coordinator().run("Customer was double-charged $40 on INV-4471. Please fix it."))
    assert main.invoices_read == ["INV-4471"]
    assert main.refunds_issued == [{"invoice_id": "INV-4471", "amount_cents": 4000}]
    calls = main.tool_calls(main.billing_runs[0])
    assert [c[0] for c in calls] == ["read_invoice", "issue_refund", "issue_refund"]
    assert "(invoice_id)" in calls[2][2]


def test_refund_above_delegated_ceiling_is_denied():
    calls = run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4001})])
    assert main.refunds_issued == []
    assert "(amount_cents)" in calls[0][2]


def test_billing_agent_cannot_read_other_invoices():
    calls = run_billing([("read_invoice", {"invoice_id": "INV-5102"})])
    assert main.invoices_read == []
    assert "(invoice_id)" in calls[0][2]


def test_streaming_run_goes_through_the_middleware():
    calls = run_billing(
        [
            ("issue_refund", {"invoice_id": "INV-5102", "amount_cents": 4000}),
            ("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4000}),
        ],
        stream=True,
    )
    assert main.refunds_issued == [{"invoice_id": "INV-4471", "amount_cents": 4000}]
    assert "(invoice_id)" in calls[0][2]


def test_coordinator_cannot_delegate_more_than_it_holds():
    with pytest.raises(MonotonicityError):
        main.billing_warrant_for("INV-4471", 60000)


def test_billing_agent_cannot_redelegate_a_wider_refund():
    child = main.billing_warrant_for("INV-4471", 4000)
    with pytest.raises(MonotonicityError):
        (
            child.grant_builder()
            .capability("issue_refund", {"invoice_id": Exact("INV-4471"), "amount_cents": Range(max=48000)})
            .holder(SigningKey.generate().public_key)
            .grant(main.billing_key)
        )


def test_wrong_holder_key_is_denied():
    stolen = main.TenuoAuthorizationMiddleware(
        main.billing_warrant_for("INV-4471", 4000),
        SigningKey.generate(),
        [main.org_key.public_key],
        [main.coordinator_warrant],
    )
    run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4000})], middleware=stolen)
    assert main.refunds_issued == []


def test_untrusted_root_is_denied():
    rogue, key = SigningKey.generate(), SigningKey.generate()
    w = Warrant.mint_builder().capability("issue_refund", {}).holder(key.public_key).ttl(60).mint(rogue)
    run_billing(
        [("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 1})],
        middleware=main.TenuoAuthorizationMiddleware(w, key, [main.org_key.public_key]),
    )
    assert main.refunds_issued == []


def test_unlisted_argument_does_not_reach_the_tool():
    # Agent Framework validates arguments against the tool schema before middleware runs,
    # so an extra argument is dropped: neither the warrant check nor the tool sees it.
    run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4000, "override": True})])
    assert main.refunds_issued == [{"invoice_id": "INV-4471", "amount_cents": 4000}]
