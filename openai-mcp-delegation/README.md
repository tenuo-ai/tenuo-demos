# Task-Scoped Authorization for OpenAI Agents over MCP

This demo asks a simple question:

> Can an agent investigate a production problem without receiving permission to
> change production?

An operator asks an OpenAI agent to investigate elevated checkout latency. The
orchestrator delegates the investigation to a worker. The worker reads metrics
and deployment state through a real FastMCP server.

The orchestrator is allowed to roll back a deployment. The worker is not. If
the worker requests a rollback, the MCP server rejects the request before the
rollback code runs.

The demo uses:

- a real OpenAI orchestrator and worker;
- a real MCP client and FastMCP server;
- signed Tenuo warrants;
- a temporary SQLite operations database.

It assumes the agent may be confused, compromised, or exposed to prompt
injection. The demo does not need to manufacture an injection. Authorization
does not depend on the model following instructions.

## The workflow

```text
Operator
   |
   v
OpenAI orchestrator                  may read and roll back checkout
   |
   | delegates only the investigation
   v
OpenAI worker                        may read checkout only
   |
   | MCP call + signed task authority
   v
Tenuo middleware                     verifies before the tool runs
   |
   v
FastMCP tool handler
   |
   v
SQLite operations state             deployment starts at 8c1e
```

The model chooses which tool to call. The server decides whether that exact
call is authorized.

## Why ordinary service access is not enough

An API key, OAuth token, or workload identity usually represents standing
access. It answers a question such as:

> May this agent service use the operations API?

The current task needs a narrower question:

> May this worker call `read_deployment(service="checkout")` as part of this
> investigation, right now?

Both checks matter. Identity establishes who is calling. Task authority limits
what that caller may do for the current unit of work.

## The authorization objects

The demo gives the orchestrator a signed **root warrant**. It permits:

- reading checkout metrics;
- reading checkout deployment state;
- rolling back a checkout deployment.

The orchestrator derives a **child warrant** for the worker. The child keeps
only the two reads. It cannot add permissions that are absent from its parent,
and it deliberately leaves rollback behind.

Each MCP call carries:

- the warrant chain back to the trusted issuer;
- the public key of the holder named by the warrant;
- a fresh holder signature over the final tool name and arguments;
- the time at which the holder created the proof.

The server checks this information before it invokes the FastMCP tool handler.

## What each run demonstrates

### 1. One agent, one tool, different arguments

Run:

```bash
uv run incident-demo baseline
```

This first run avoids delegation. It shows why permission to use a tool is not
enough by itself.

| Call | Result | Meaning |
|---|---:|---|
| `read_metrics(service="checkout")` | Allow | This task permits checkout metrics. |
| `read_metrics(service="payments")` | Deny | The tool exists, but payments is outside this task. |

Both calls match the tool's JSON schema. The difference comes from the task's
argument constraint.

### 2. A normal agent investigation

Run:

```bash
uv run incident-demo agent
```

The OpenAI orchestrator delegates the investigation to a worker. At that
handoff, the orchestrator derives a fresh, read-only child warrant for the
worker invocation. The worker chooses the two permitted reads and uses the
protected MCP server.

This run shows that the authorization layer fits a normal agent workflow. The
deterministic cases below make the security claims reproducible without a model
or network connection.

### 3. Five deterministic delegation cases

Run:

```bash
uv run incident-demo cases
```

| Scenario | Result | What it demonstrates |
|---|---:|---|
| Worker reads checkout deployment | Allow | The child warrant permits this operation and `service="checkout"`. |
| Worker requests rollback | Deny | Delegation is subtractive. The parent has rollback authority, but the child does not. |
| A different key presents the worker's chain | Deny | A valid chain is unusable without proof that the caller is its intended holder. |
| Worker presents the child without its parent | Deny | The server needs a verifiable path from the child back to a trusted issuer. |
| Worker presents an expired child | Deny | Authority ends when the task grant expires. |

After those calls, the demo reads the protected state again:

```text
deployment=8c1e, rollbacks_executed=0
```

This is more than a printed denial. The unchanged state proves that the
unauthorized rollback never reached the rollback handler.

## Plain-language glossary

**Task authority**
: Permission created for one unit of work rather than for the full lifetime of
  an agent or service.

**Warrant**
: A signed task grant describing the holder, permitted operations, argument
  constraints, parent grant, and expiration.

**Delegation**
: Deriving a child warrant for another worker. The child may keep or remove
  authority but cannot add authority absent from its parent.

**Warrant chain**
: The child warrant plus its parents, allowing a server to verify the path back
  to an issuer it trusts.

**Holder proof**
: A fresh signature showing that the caller possesses the key named by the
  warrant. The signature covers the final tool name and arguments.

**Effect boundary**
: The point immediately before application code creates a real effect. In this
  demo, Tenuo middleware protects that boundary in the MCP server.

## Run the demo

Requirements:

- Python 3.11 or newer;
- [`uv`](https://docs.astral.sh/uv/);
- an OpenAI API key only for the live-agent run.

Install dependencies and run the deterministic paths:

```bash
cd openai-mcp-delegation
uv sync --extra dev
uv run incident-demo baseline
uv run incident-demo cases
```

Run the OpenAI orchestrator and worker:

```bash
export OPENAI_API_KEY="your-key"
# Optional override; the tested default is gpt-5-mini.
export OPENAI_MODEL="gpt-5-mini"
uv run incident-demo agent
```

The project does not automatically load `.env` files. `.env.example` is a
shell export template; source it only after replacing its placeholders. Pin
`OPENAI_MODEL` if you rehearse with a model other than the tested
`gpt-5-mini` default.

Run the rehearsal helper:

```bash
./scripts/rehearse.sh
```

When `OPENAI_API_KEY` is absent, the rehearsal skips the live-agent portion and
still runs the complete authorization path.

## Where the implementation lives

- [`authority.py`](src/incident_demo/authority.py) creates the orchestrator
  warrant, derives a read-only worker warrant at handoff, builds the chain,
  and signs each final call.
- [`mcp_client.py`](src/incident_demo/mcp_client.py) attaches the warrant chain
  and holder proof to MCP `_meta` after the tool name and arguments are final.
- [`ops_server.py`](src/incident_demo/ops_server.py) installs Tenuo verification
  as FastMCP middleware before the tool handlers and emits stable `ALLOWED` or
  `DENIED` audit lines for each authorization decision.
- [`agents.py`](src/incident_demo/agents.py) defines the OpenAI orchestrator and
  worker-as-tool workflow.
- [`scenarios.py`](src/incident_demo/scenarios.py) runs the baseline, the five
  delegation cases, and the protected-state assertion.
- [`state.py`](src/incident_demo/state.py) implements the temporary SQLite
  operations state.

## What this demo does not claim

Task authorization constrains which operations may execute. It does not:

- make an allowed model decision correct or wise;
- prevent misuse of an operation that the task legitimately permits;
- stop bypass if raw downstream credentials remain available to the agent;
- replace sandboxing, network isolation, or information-flow controls;
- provide production replay protection for non-idempotent writes by itself.

Production systems should combine task authority with existing identity,
credential isolation, key management, replay controls, and operational policy.

## Stage-safe operation

`baseline` and `cases` require no model or network access. They still use the
real MCP transport, middleware, signatures, warrant chain, and stateful backend.

The demo generates new keys and a temporary SQLite database for each run. It
does not connect to a production control plane.
