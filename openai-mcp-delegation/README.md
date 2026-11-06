# Authority That Survives Agent Delegation

Let an agent investigate production without giving it permission to change
production.

An orchestrator can investigate and roll back a deployment. It delegates the
investigation to a worker with read-only permission. Tenuo allows the worker's
read, blocks its rollback attempt, and produces a signed record of the denial.

## Run it

Requirements: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
./run-demo.sh
```

No API key or account is required. The launcher installs dependencies on the
first run; after installation, the demo runs locally without network access.
It uses scripted tool calls so you get the same result every time, with real
MCP requests, authorization checks, and a local database.

Expected output:

```text
Tenuo: authority that survives delegation

ISSUE     orchestrator: investigate checkout + rollback
DELEGATE  worker: investigate checkout only
ALLOW     worker -> read_deployment(service=checkout)
DENY      worker -> rollback_deployment(service=checkout) — rollback was not delegated
VERIFY    deployment=8c1e, rollbacks=0
VERIFY    signed denial receipt valid offline (.tenuo-demo/)
```

The first verification proves the denied call never changed protected state.
The second verifies the enforcement point's signed denial receipt locally,
including its signer, action, outcome, and signature. It also leaves the
receipt and verification keys in `.tenuo-demo/`, so you can verify it in a
separate process:

```bash
uv run tenuo receipt verify .tenuo-demo/denial-receipt.txt \
  --authorizer "$(<.tenuo-demo/enforcement-public-key.hex)" \
  --root "$(<.tenuo-demo/trusted-root.hex)" \
  --args '{"service":"checkout","deployment":"8c1e"}'
```

## What happened

The orchestrator holds a signed permission grant, called a **warrant**, that
permits reads and rollback. It creates a child warrant for the worker containing
only checkout reads. A child can remove permissions but cannot add permissions
absent from its parent.

Each MCP call carries the warrant chain and a fresh holder signature over the
final tool name and arguments. Tenuo middleware verifies both before invoking
the tool. The model or harness can request rollback; it cannot make the server
execute rollback without the corresponding authority.

## The workflow

The default run scripts the orchestrator and worker calls. The optional
[live-agent run](#live-openai-agents) uses OpenAI agents in those same roles.

```text
Operator
   |
   v
Orchestrator                         may read checkout/payments; roll back checkout
   |
   | delegates only the investigation
   v
Worker                               may read checkout only
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

In either run, the server decides whether each exact call is authorized.

## Why service identity is not enough

An API key, OAuth token, or workload identity usually represents standing
access. It answers a question such as:

> May this agent service use the operations API?

The current task needs a narrower question:

> May this worker call `read_deployment(service="checkout")` as part of this
> investigation, right now?

Both checks matter. Identity establishes who is calling. Task authority limits
what that caller may do for the current unit of work.

## Explore further

The short path is the default:

```bash
uv run incident-demo
```

### One tool, different arguments

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

### Live OpenAI agents

Run:

```bash
export OPENAI_API_KEY="your-key"
uv run incident-demo agent
```

The OpenAI orchestrator delegates the investigation to a worker. At that
handoff, the orchestrator derives a fresh, read-only child warrant for the
worker invocation. The worker chooses the two permitted reads and uses the
protected MCP server.

The tested default is `gpt-5-mini`; override it with `OPENAI_MODEL`.

### Seven deterministic delegation cases

Run:

```bash
uv run incident-demo cases
```

These scripted cases require no API key. Add `--step` to pause before each
call while presenting. The `baseline` command supports `--step` too.

| Scenario | Result | What it demonstrates |
|---|---:|---|
| Orchestrator reads payments deployment | Allow | The parent warrant permits the tool for both checkout and payments. |
| Worker reads checkout deployment | Allow | The child warrant permits this operation and `service="checkout"`. |
| Worker reads payments deployment | Deny | Delegation retained the tool but narrowed its service argument from `{checkout, payments}` to `{checkout}`. |
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

## Where the implementation lives

- [`authority.py`](src/incident_demo/authority.py) creates the orchestrator
  warrant, derives a read-only worker warrant at handoff, builds the chain,
  and signs each final call.
- [`mcp_client.py`](src/incident_demo/mcp_client.py) attaches the warrant chain
  and holder proof to MCP `_meta` after the tool name and arguments are final.
- [`ops_server.py`](src/incident_demo/ops_server.py) installs Tenuo verification
  before the handlers and signs enforcement receipts for the decisions.
- [`agents.py`](src/incident_demo/agents.py) defines the OpenAI orchestrator and
  worker-as-tool workflow.
- [`scenarios.py`](src/incident_demo/scenarios.py) runs the six-line canonical
  path, the seven advanced cases, and the protected-state assertions.
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
