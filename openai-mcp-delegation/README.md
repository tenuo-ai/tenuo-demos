# Task-Scoped Authorization for OpenAI Agents over MCP

A small, stageable demo of authority moving with work.

An operator asks an OpenAI agent to investigate elevated checkout latency. The
orchestrator delegates the investigation to a worker, which calls a real
FastMCP operations server. The orchestrator can read and roll back deployments;
the worker receives a child warrant that permits only the two reads needed for
the investigation.

The demo first establishes task scope with one agent and one server: checkout
metrics are allowed, while the same tool for an unrelated service is denied.
It then introduces delegation.

The demo assumes an agent can be confused or compromised. It does not depend on
manufacturing a prompt injection. The authorization boundary is the MCP server,
which verifies every tool call before application code runs.

## Architecture

```text
Operator
   |
   v
OpenAI orchestrator                 authority: read + rollback
   |
   | delegates investigation
   | derives signed child warrant
   v
OpenAI incident worker             authority: read only
   |
   | MCP call + warrant chain + proof of possession
   v
Tenuo middleware -> FastMCP tools  enforcement before tool execution
   |
   v
SQLite operations state            checkout deployment 8c1e
```

This is not a replacement for the identity and access controls protecting the
MCP server. It adds a narrower question at the tool boundary: *is this holder
authorized to make this exact call as part of this task, right now?*

## What the deterministic runs prove

The `baseline` command makes the tool-level boundary visible before delegation:

| Call | Expected | Why |
|---|---:|---|
| Read metrics for `checkout` | Allow | The task warrant permits this tool and service. |
| Read metrics for `payments` | Deny | The tool exists, but that argument is outside this task. |

The `cases` command uses a real stdio MCP connection and executes four calls:

| Case | Expected | Why |
|---|---:|---|
| Worker reads the checkout deployment | Allow | The tool and `service=checkout` are in the child warrant. |
| Worker attempts a rollback | Deny | The parent has rollback authority, but the child does not. |
| Worker presents only the child warrant | Deny | The server cannot verify its delegation path to a trusted root. |
| Worker presents an expired child warrant | Deny | The grant is no longer valid. |

The last assertion rereads the state and proves that the denied rollback never
reached the application handler.

## Run it

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and an OpenAI API
key only for the live-agent portion.

```bash
cd openai-mcp-delegation
uv sync --extra dev
uv run incident-demo baseline
uv run incident-demo cases
```

Run the actual OpenAI orchestrator and worker:

```bash
export OPENAI_API_KEY="your-key"
# Optional: export OPENAI_MODEL="your-model"
uv run incident-demo agent
```

Or rehearse both paths, skipping the model call when `OPENAI_API_KEY` is absent:

```bash
./scripts/rehearse.sh
```

## Where to look

- [`authority.py`](src/incident_demo/authority.py) mints the orchestrator warrant,
  attenuates it for the worker, constructs the chain, and signs each call.
- [`mcp_client.py`](src/incident_demo/mcp_client.py) attaches the warrant chain and
  proof of possession to MCP `_meta` after tool name and arguments are final.
- [`ops_server.py`](src/incident_demo/ops_server.py) installs Tenuo verification as
  FastMCP middleware, before the tool handlers.
- [`agents.py`](src/incident_demo/agents.py) defines the OpenAI orchestrator and
  worker-as-tool choreography.
- [`scenarios.py`](src/incident_demo/scenarios.py) runs the four deterministic
  authorization cases used on stage.

The adapter around MCP is intentional. Authorization proof is bound to the
final tool name and arguments, so generating it at the point of the MCP call
avoids trusting earlier model text or mutable workflow state.

## Stage-safe operation

Use `uv run incident-demo baseline` and `uv run incident-demo cases` for the
security claims. They require no model or network access and still use the real
MCP transport, middleware, signatures, and stateful backend. The live agent
establishes that this is a normal agent workflow; it is not required to make
the allow/deny outcomes reliable.

The demo uses generated keys and a temporary SQLite database on every run. It
does not connect to a production control plane.
