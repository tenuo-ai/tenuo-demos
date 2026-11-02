# Task-scoped authority for a Strands sub-agent

A customer was double-charged $40 on invoice INV-4471. A support coordinator
hands the ticket to a billing sub-agent, and the billing agent is allowed to
fix it: read that invoice, and refund up to $40 on it. Nothing else.

The invoice carries a planted note asking for a refund on a different
invoice. The model follows it. The refund on INV-4471 goes through; the one
on INV-5102 is cancelled before the tool body runs.

```text
coordinator    refund <= $500 on any invoice
   |
   | ask_billing_agent(invoice_id="INV-4471", max_refund_cents=4000)
   v
billing_agent  read_invoice(invoice_id == "INV-4471")
               issue_refund(invoice_id == "INV-4471", amount_cents <= 4000)
```

## Run it

```bash
uv run main.py
```

```text
  coordinator -> ask_billing_agent({'invoice_id': 'INV-4471', 'max_refund_cents': 4000, ...})  ALLOWED
  billing_agent -> read_invoice({'invoice_id': 'INV-4471'})  ALLOWED
  billing_agent -> issue_refund({'invoice_id': 'INV-4471', 'amount_cents': 4000})  ALLOWED
  billing_agent -> issue_refund({'invoice_id': 'INV-5102', 'amount_cents': 4000})  DENIED  Not authorized by warrant: issue_refund (invoice_id)

refunds issued: [{'invoice_id': 'INV-4471', 'amount_cents': 4000}]
```

No API key or network access needed. A scripted model plays the LLM so
the run is the same every time.

## Where enforcement happens

`TenuoAuthorization` is a Strands `HookProvider`. On every
`BeforeToolCallEvent` it checks the call's name and arguments against the
agent's warrant with `tenuo.enforce_tool_call`. On a denial it sets
`event.cancel_tool`, so Strands returns an error result to the model and never
calls the tool. Errors inside the check also cancel the call.

The billing agent's warrant is minted when the coordinator delegates, from the
coordinator's own warrant. Tenuo refuses to grant a child more than its parent
holds, so the coordinator cannot hand out a $600 refund, and the billing agent
cannot pass on more than $40.

The warrant is closed-world: an argument the warrant doesn't name is denied,
so the model can't add `override=True` to get around a constraint.

## Tests

```bash
uv run pytest
```

The tests count what the tools actually did:

- the delegated $40 refund runs once; the injected refund runs zero times
- $40.01 on INV-4471 is denied, and so is reading INV-5102
- the coordinator can't delegate more than $500; the billing agent can't re-delegate more than $40
- a stolen warrant used with the wrong key, a warrant from an untrusted root, and an extra argument are all denied
- calling a tool directly with `agent.tool.issue_refund(...)` goes through the same hook

Tested with strands-agents 1.61.1 and tenuo 0.3.2.
