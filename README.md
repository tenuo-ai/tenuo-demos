# Tenuo Demos

Open source demos showing how [Tenuo](https://tenuo.ai) protects AI agents with cryptographic capability tokens.

## Demos

| Demo | What it shows |
|------|--------------|
| [**Invoice Processing**](invoice-processing/) | A multi-agent pipeline processes invoices. A prompt injection redirects a payment to the wrong bank account. Traditional auth (OAuth, RBAC, policy engines) all approve. Tenuo blocks it. |
| [**Skyvern Prompt Injection**](skyvern-prompt-injection/) | An AI shopping agent browses an e-commerce store. A hidden prompt injection tricks it into buying a terrible product. Tenuo's warrant constraints block the bad purchase — the LLM is compromised but the outcome isn't. |
| [**Temporal Incident Response**](temporal-incident-response/) | An AI on-call agent triages a production incident as a Temporal workflow. Investigation runs autonomously; the production restart is gated by a cryptographically signed human approval; the receipt chain is offline-verifiable end-to-end. |
| [**Temporal Order Repair**](temporal-order-repair/) | Josh Smith's multi-agent order-repair demo on Temporal, with a warrant per order. Poisoned customer notes get the planner to route an approval to the wrong person and order 5,000 badge sets; the warrant refuses the first and holds the second for signed approval. Approvals arrive as Temporal Signals, and every checked call gets an offline-verifiable receipt. |
| [**Claude Agent SDK on Temporal**](temporal-claude-agent-sdk/) | Temporal's Claude Agent SDK plugin runs each tool call as a durable Activity; a Tenuo Worker interceptor checks each call and its exact arguments against a task warrant first. An over-limit refund and an undelegated delete never reach the tool, and a Temporal approval alone can't authorize a bigger refund until a new warrant is issued. |
| [**OpenAI + MCP Delegation**](openai-mcp-delegation/) | An OpenAI orchestrator delegates incident investigation to a worker. The worker keeps a deployment-read tool with narrower service arguments, while the server also rejects an undelegated rollback, a stolen chain, a detached child warrant, and an expired grant. |

## Running a demo

Each demo is self-contained: its folder has its own dependencies, setup steps and README. Clone the repo, `cd` into the demo, and follow its README.

| Demo | You need | Start with |
|------|----------|------------|
| Invoice Processing | Python, Docker, an Anthropic API key | [Quick Start](invoice-processing/README.md#quick-start) |
| Skyvern Prompt Injection | Python, Skyvern, a Tenuo Cloud account | [tutorial-guide.md](skyvern-prompt-injection/tutorial-guide.md) |
| Temporal Incident Response | Python, the Temporal CLI | [Quickstart](temporal-incident-response/README.md#quickstart): `temporal server start-dev`, then `make setup && make demo` |
| Temporal Order Repair | Python 3.12, Poetry, the Temporal CLI, an LLM API key | [Run it locally](temporal-order-repair/README.md#run-it-locally), summarized below |
| Claude Agent SDK on Temporal | Python 3.10+, uv, git, the Temporal CLI (no API key) | [Run it](temporal-claude-agent-sdk/README.md#run-it): `bash run_e2e.sh` |
| OpenAI + MCP Delegation | Python 3.11+, `uv`; an OpenAI API key only for the live agent | [Run the demo](openai-mcp-delegation/README.md#run-the-demo): `uv sync --extra dev`, then `uv run incident-demo cases` |

### Temporal Order Repair

```bash
cd temporal-order-repair
poetry install
cp .env.example .env                 # set LLM_MODEL and LLM_KEY
temporal server start-dev            # terminal 1

poetry run python create_tenuo_keys.py          # writes one key file per role
poetry run python run_worker.py                 # terminal 2: the agents
poetry run python run_issuer_worker.py          # terminal 3: issues a warrant per order
poetry run python run_repair_tools_worker.py    # terminal 4: the repair tools, warrant required

poetry run python poison_order_notes.py         # optional: poison two customer notes
poetry run python run_repair_agent.py           # answer "yes" to approve the plan
poetry run python approve_repair_call.py --as store-manager   # then --as finance
poetry run tenuo receipt chain receipts/repair-tools.jsonl     # verify the receipts offline
```

The tests need no LLM key: they feed the agents a recorded plan instead of calling a model. If `TEMPORAL_ADDRESS` is set, in your shell or in `.env`, they use that server, so keep `temporal server start-dev` running. Without it they start their own local dev server (downloaded on first run).

```bash
cd temporal-order-repair
poetry run pip install pytest pytest-asyncio
poetry run python -m pytest tests
```

## What is Tenuo?

AI agents need access to production systems — databases, APIs, payment processors. Traditional authorization (OAuth scopes, RBAC roles, policy engines) answers **"is this agent allowed to do this?"** The answer is yes. The problem is that's the wrong question.

Tenuo issues **cryptographic capability tokens** that answer a different question: **"what should this agent be doing right now, with these specific arguments, for how long?"** The token carries per-argument constraints derived from the task context and is enforced in microseconds with no network round-trip.

- **Open source core**: [github.com/tenuo-ai/tenuo](https://github.com/tenuo-ai/tenuo)
- **Integrations**: LangGraph, LangChain, CrewAI, OpenAI, MCP, Google ADK, Temporal
- **Cloud dashboard**: [cloud.tenuo.ai](https://cloud.tenuo.ai)
- **Early access**: [tenuo.ai/early-access.html](https://tenuo.ai/early-access.html)

## License

MIT
