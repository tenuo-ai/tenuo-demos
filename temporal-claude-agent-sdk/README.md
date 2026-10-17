# Claude Agent SDK on Temporal, with Tenuo authorization

Temporal's [Claude Agent SDK plugin](https://github.com/temporalio/ai-integrations/pull/33) runs each of Claude's tool calls as its own durable Activity, so retries, Worker crashes and approvals are Temporal's problem rather than yours. What it doesn't decide is whether the agent should be making that call at all. This demo adds that check with Tenuo. A Worker interceptor checks every tool call, with its exact arguments, against a short-lived warrant before the tool runs.

```text
Claude Agent SDK
      |
      v
Temporal tool Activity (run_claude_tool_step)
      |
      v
Tenuo Worker interceptor
      |
      +--> warrant allows this tool + these args --> run
      |
      +--> warrant denies -------------------------> tool never runs
```

Temporal still owns execution, retries, Worker recovery, workflow state and approvals. Tenuo only decides whether this exact call is authorized. The two compose: an approval can lead to new authority being issued, but an approval on its own never authorizes anything.

> **Pinned to an unreleased plugin.** The plugin is still in draft PR [temporalio/ai-integrations#33](https://github.com/temporalio/ai-integrations/pull/33) and isn't on PyPI yet. `requirements.txt` installs it from git at that PR's head, `4f791d0`. We'll move this demo to the released package once the PR merges.

## Run it

You'll need Python 3.10+, [`uv`](https://docs.astral.sh/uv/), `git` and the [Temporal CLI](https://docs.temporal.io/cli).

```bash
bash run_e2e.sh
```

The script creates a throwaway environment, installs the pinned plugin and the pinned Tenuo release, and starts a temporary Temporal dev server. Then it runs every test, including the real Claude Agent SDK and its bundled Claude Code engine. The model is the plugin's own deterministic local Messages API stand-in, fetched from the same pinned commit, so no API key is needed. It stops the server on exit and prints a folder with the server log, JUnit results and the lifecycle trace. Set `TEMPORAL_DEMO_PORT` if port 17333 is taken.

For only the tests that don't need a server:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m pytest -q tests/test_boundary.py tests/test_setup.py tests/test_pin.py
```

For the scripted demo against a Temporal server you already have running:

```bash
.venv/bin/python run_demo.py --address localhost:7233
```

`run_demo.py --live` uses your Claude authentication and a real model. The fake-model tests are the repeatable evidence. To try another Claude Code version, set `CLAUDE_CLI_PATH`. Otherwise the SDK's bundled engine is used.

## Four cases

The shop records every time a tool's implementation is entered, before it does anything, and keeps refunds in a separate ledger. A ten-minute task warrant grants:

```python
get_order: order_id=Exact("order-123")
issue_refund: order_id=Exact("order-123"), amount=Range(min=0, max=100)
```

| Case | What Claude asks for | Implementation entered | Result |
|---|---|---|---|
| A | `get_order("order-123")` | 1 | normal result |
| B | `issue_refund("order-123", 25)` | 1 | normal result, one refund |
| C | `issue_refund("order-123", 500)` | 0 | denied |
| D | `delete_order("order-123")` | 0 | denied |

`delete_order` exists on the MCP server but isn't in the warrant, so D tests authorization, not an unknown-tool lookup. None of the tools checks policy itself.

On the pinned plugin, Claude is told a denied call "may have run", even though the tests prove it didn't. The plugin has no way yet for middleware to say "refused before it ran". We've proposed one upstream: a vendor-neutral `ToolCallRefused` error type. Once it lands, this demo will raise it, and Claude will be told the call was refused and didn't run.

## The adapter

Claude names the MCP operation `mcp__shop__issue_refund`, and every Claude Code tool call arrives as the same Activity, `run_claude_tool_step`. So authorizing the Activity name alone would enforce nothing about `amount`. The [adapter](adapter.py) reads `step.call.name` and `step.call.input`, strips the known `mcp__shop__` prefix, and checks `issue_refund` with the exact arguments.

Signing on the way out and checking on the way in use the same mapping. Everything else comes from Tenuo's existing Temporal interceptor: chain verification, proof-of-possession, authorization, audit and replay suppression. The original `ToolStepInput` reaches the Activity unchanged, and each check uses its own config, so no shared mapping is mutated.

Built-in tools and ordinary durable tools are turned off, and every shop tool matches `tool_activities=["mcp__shop__*"]`, so each call pauses for its own Activity. The model segment rejects input that breaks those settings.

The adapter uses private APIs from Tenuo 0.3.2, kept in one file. It's demo code, not a supported plugin API. Replay suppression is in-process here; a distributed deployment needs Tenuo's shared store and idempotent services.

## Authority lifecycle

The [lifecycle scenario](LIFECYCLE.md) uses a controller-issued, ten-minute warrant tied to the Workflow and one order:

1. Reading the order and refunding 25 succeed.
2. Refunding 250 is denied.
3. A Temporal approval Update arrives, and 250 is still denied, because approval alone doesn't grant authority.
4. The controller signs a new warrant, and the retry succeeds.

The tests also restart the Worker after the new warrant is issued, and check that no private key ever appears in workflow history.

```bash
python run_lifecycle.py --address localhost:7233 --restart
```

The lifecycle uses a separate, explicit mode where the Worker holds an identity and creates fresh proofs when the Activity starts. The baseline keeps proofs from scheduling time, with their queue-delay limit. [LIFECYCLE.md](LIFECYCLE.md) covers both trust models, expiry, retries, long approval waits and what we'd recommend in production. [TECHNICAL_NOTE.md](TECHNICAL_NOTE.md) traces the exact enforcement and denial path through the plugin.

## What this demo doesn't do

- It doesn't evaluate a hosted model's judgement. The model is scripted, so the tests are deterministic.
- It doesn't claim exactly-once effects for distributed services or across Continue-As-New.
- It doesn't translate Tenuo's denial into the plugin's refusal signal yet; that waits on the upstream change above.

## License

MIT
