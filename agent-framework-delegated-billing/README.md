# Task-scoped authority for an Agent Framework sub-agent

Your coordinator can refund up to $500. When it hands a ticket to a billing
sub-agent, should the sub-agent get all of that? Here it gets exactly what the
ticket needs: read INV-4471, refund up to $40 on INV-4471. It can still act,
it just can't act on anything else.

The invoice carries a planted note asking for a refund on a different invoice.
The model follows it. The $40 refund on INV-4471 goes through; the one on
INV-5102 never reaches the tool.

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

No API key needed: a scripted chat client plays the model so the run is the
same every time. `uv run --extra live main.py --live` swaps in
`OpenAIChatClient` (set `OPENAI_API_KEY`).

## Where enforcement happens

`TenuoAuthorizationMiddleware` is a `FunctionMiddleware`. For every tool call it
checks the tool name and the validated arguments against the agent's warrant
with `tenuo.enforce_tool_call`. On a denial it sets `context.result` and skips
`call_next()`, so the tool body never runs and the model sees the denial as
the tool result. Errors inside the check deny too.

The billing agent's warrant is minted at delegation time from the
coordinator's own warrant. Tenuo refuses to grant a child more than its
parent holds, so the coordinator can't hand out a $600 refund and the billing
agent can't pass on more than its $40. Constraints are per argument, so this
isn't a tool allowlist: the same `issue_refund` tool is allowed for one
invoice and amount and denied for others.

One thing to watch: Agent Framework skips middleware it can't categorize with
only a log warning. If you build a custom chat client, keep
`FunctionInvocationLayer` before `ChatMiddlewareLayer` (as the built-in
clients do), or function middleware never runs.

## Tests

```bash
uv run pytest
```

The tests count what the tools actually did:

- the delegated $40 refund runs once; the injected refund runs zero times
- $40.01 on INV-4471 is denied, and so is reading INV-5102
- a streaming run (`run(stream=True)`) goes through the same middleware
- the coordinator can't delegate more than $500; the billing agent can't re-delegate more than $40
- a warrant used with the wrong key, or from an untrusted root, is denied
- an argument that isn't in the tool schema never reaches the tool

Tested with agent-framework-core 1.22.0 and tenuo 0.3.2. The same scenario
for Strands is in [`../strands-delegated-billing`](../strands-delegated-billing).
