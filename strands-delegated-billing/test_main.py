import pytest
from strands import Agent
from tenuo import Exact, Range, SigningKey, Warrant
from tenuo.exceptions import MonotonicityError

import main


@pytest.fixture(autouse=True)
def reset():
    main.refunds_issued.clear()
    main.invoices_read.clear()
    main.billing_runs.clear()


def run_billing(script, hook=None):
    agent = main.make_billing_agent("INV-4471", 4000, script + ["done"])
    if hook is not None:
        agent = Agent(
            name="billing_agent",
            model=main.ScriptedModel(script + ["done"]),
            tools=[main.read_invoice, main.issue_refund],
            hooks=[hook],
            callback_handler=None,
        )
    agent("go")
    return main.tool_calls(agent)


def test_delegated_refund_runs_once_and_injected_refund_never_runs():
    main.make_coordinator()("Customer was double-charged $40 on INV-4471. Please fix it.")
    assert main.invoices_read == ["INV-4471"]
    assert main.refunds_issued == [{"invoice_id": "INV-4471", "amount_cents": 4000}]
    calls = main.tool_calls(main.billing_runs[0])
    assert [c[2] for c in calls] == ["success", "success", "error"]
    assert "(invoice_id)" in calls[2][3]


def test_refund_above_delegated_ceiling_is_denied():
    calls = run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4001})])
    assert main.refunds_issued == []
    assert "(amount_cents)" in calls[0][3]


def test_billing_agent_cannot_read_other_invoices():
    calls = run_billing([("read_invoice", {"invoice_id": "INV-5102"})])
    assert main.invoices_read == []
    assert "(invoice_id)" in calls[0][3]


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
    stolen = main.TenuoAuthorization(
        main.billing_warrant_for("INV-4471", 4000),
        SigningKey.generate(),
        [main.org_key.public_key],
        [main.coordinator_warrant],
    )
    run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4000})], hook=stolen)
    assert main.refunds_issued == []


def test_untrusted_root_is_denied():
    rogue, key = SigningKey.generate(), SigningKey.generate()
    w = Warrant.mint_builder().capability("issue_refund", {}).holder(key.public_key).ttl(60).mint(rogue)
    run_billing(
        [("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 1})],
        hook=main.TenuoAuthorization(w, key, [main.org_key.public_key]),
    )
    assert main.refunds_issued == []


def test_unlisted_argument_does_not_slip_through():
    calls = run_billing([("issue_refund", {"invoice_id": "INV-4471", "amount_cents": 4000, "override": True})])
    assert main.refunds_issued == []
    assert "(override)" in calls[0][3]


def test_direct_tool_call_goes_through_the_hook():
    agent = main.make_billing_agent("INV-4471", 4000, [])
    denied = agent.tool.issue_refund(invoice_id="INV-5102", amount_cents=4000)
    allowed = agent.tool.issue_refund(invoice_id="INV-4471", amount_cents=4000)
    assert denied["status"] == "error" and allowed["status"] == "success"
    assert main.refunds_issued == [{"invoice_id": "INV-4471", "amount_cents": 4000}]
