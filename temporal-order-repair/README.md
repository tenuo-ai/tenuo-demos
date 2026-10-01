# Temporal order repair with Tenuo warrants

Josh Smith's [temporal-multi-agent-order-repair](https://github.com/joshmsmith/temporal-multi-agent-order-repair) (MIT, see [LICENSE](./LICENSE)) with [Tenuo](https://github.com/tenuo-ai/tenuo) warrants added. Josh's agents detect, analyze, plan, execute and report on broken Hogwarts school-supply orders. This version gives each order its own warrant and checks every repair tool call against it, on the worker that runs the tool, before the tool runs.

Josh's original README, with the full walkthrough of the agents, MCP setup and the proactive and scheduled agents, is in [README.upstream.md](./README.upstream.md).

## What changed from Josh's demo

- Each repair tool (`request_payment_update_tool`, `order_inventory_tool`, `request_approval_tool`) runs as its own Activity on a separate repair-tools worker ([`run_repair_tools_worker.py`](./run_repair_tools_worker.py)). That worker runs Tenuo's Temporal plugin with `require_warrant=True` and holds only public keys.
- After the plan is approved, an issuer worker ([`run_issuer_worker.py`](./run_issuer_worker.py)) issues a one-hour warrant per order, filled in from the order record, never from the plan:
  - payment requests only to that order's customer
  - approval requests only to the shop's approvals desk (`approve-orders@diagonalley.co.uk`)
  - restocks of up to 100 of an item on the order run on their own; larger restocks, or items not on the order, need every approver named in the warrant to sign that exact call
  - nothing over 10,000 runs, signed or not
- Approvals reach the Workflow as a `ToolCallDecision` Signal carrying the approvers' signatures, which the repair-tools worker verifies before the tool runs ([`approve_repair_call.py`](./approve_repair_call.py)).
- Every call the repair-tools worker checks gets a signed receipt in `receipts/repair-tools.jsonl`, verifiable offline with `tenuo receipt chain`.
- With Tenuo turned on, the workflow worker refuses to run repairs inline, so every tool call goes through the check. Without Tenuo's key files, the demo runs exactly as Josh wrote it.
- [`poison_order_notes.py`](./poison_order_notes.py) edits two customer notes to show what the warrants stop: Hagrid asks for the approval request to go to him, and Hermione asks for 5,000 badge sets.

The Workflow change is small; see `execute_repair` and the `ToolCallDecision` Signal in [`workflows.py`](./workflows.py). Everything else lives in [`tenuo_repair.py`](./tenuo_repair.py).

## Requirements

- Python 3.12 and [Poetry](https://python-poetry.org/)
- The [Temporal CLI](https://docs.temporal.io/cli) for `temporal server start-dev`
- An LLM API key for the planner ([LiteLLM](https://docs.litellm.ai/) model names, e.g. `openai/gpt-4o-mini`)
- Tenuo 0.3.2 or later

## Run it locally

```bash
poetry install
cp .env.example .env                 # set LLM_MODEL and LLM_KEY
temporal server start-dev            # terminal 1

python tenuo_repair.py keygen        # root (keep offline), issuer, worker, tools and approver key files
python run_worker.py                 # terminal 2: Josh's agents
python run_issuer_worker.py          # terminal 3: issues a warrant per order
python run_repair_tools_worker.py    # terminal 4: the repair tools, warrant required

python poison_order_notes.py         # optional: poison two customer notes (undo with: git checkout data/)
python run_repair_agent.py           # approve the plan when asked
python approve_repair_call.py --as store-manager   # then --as finance; add --no to deny
tenuo receipt chain receipts/repair-tools.jsonl     # verify the signed receipts offline
```

`keygen` writes one env file per role (`tenuo-root.env`, `tenuo-issuer.env`, `tenuo-worker.env`, `tenuo-tools.env`, `tenuo-approver-*.env`). They're gitignored. In a real deployment each goes to a different machine, and the root key stays offline; you only need it again to renew the issuer's warrant (`python tenuo_repair.py renew-issuer`).

## What to look for

With the poisoned notes and the plan approved:

| Planned repair | Temporal only | Temporal + Tenuo |
|---|---|---|
| Ask Harry to update his payment | Sent | Sent |
| Ask Ron to update his payment | Sent | Sent |
| Send Hagrid's approval request to `hagrid@hogwarts.edu` | Sent to Hagrid | Refused by the warrant |
| Order 5,000 badge sets for Hermione | Ordered | Held for approval |

In the Temporal Web UI (http://localhost:8233) you'll see an `issue_order_warrant` Activity per order, the refused call as a non-retryable Activity failure naming the broken constraint, and the `ToolCallDecision` Signal that ends the approval wait.

## Tenuo Cloud (optional)

With [Tenuo Cloud](https://cloud.tenuo.ai) (free plan for developers), the root key stays in Tenuo Cloud's KMS, a trigger issues each order's warrant, approvers decide in the dashboard or Slack, and receipts are uploaded for search. The workers still make every decision locally.

In Tenuo Cloud, create:

- a warrant template and an `order-repair` trigger that fills it from an `order` event (`order.order_id`), allowed for a service account
- an approval policy for the restock gate
- a webhook for `approval.approved`, `approval.denied` and `approval.expired`, pointing at [`run_approval_webhook.py`](./run_approval_webhook.py) (it listens on `:8088/tenuo`; use a tunnel for local runs)

Then add a `tenuo-cloud.env`:

```bash
TENUO_API_KEY=...                  # service-account key
TENUO_ORDER_REPAIR_TRIGGER=...     # trigger ID
TENUO_CLOUD_TRUSTED_ROOT=...       # the tenant's root public key
TENUO_APPROVAL_POLICY=...          # approval policy ID
TENUO_WEBHOOK_SECRET=...           # from the webhook you created
```

and run `python run_approval_webhook.py` alongside the other workers.

## Tests

```bash
TEMPORAL_ADDRESS=localhost:7233 python -m pytest tests   # needs pytest and pytest-asyncio
```

The tests run the Workflow with all three workers in-process, including a replay check that the Tenuo path is deterministic.
