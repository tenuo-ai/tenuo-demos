# Invoice Processing Demo

A multi-agent pipeline that processes invoices, verifies vendors, and executes payments. Built on [LangGraph](https://github.com/langchain-ai/langgraph).

This demo shows a prompt injection that redirects a $14,200 payment to the wrong bank account — through four layers of properly configured authorization. Then shows how [Tenuo](https://tenuo.ai) blocks it.

## Quick Start

Only two real services are required: **Postgres** and **OPA**. The GCP SA,
OAuth, and SpiceDB auth layers all run in-memory — no cloud accounts or
additional services needed.

```bash
cd invoice-processing

# 1. Set up
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 2. Start infrastructure (only postgres and OPA needed locally)
docker compose up -d postgres opa

# 3. Seed the database
python -m db.seed

# 4. Start servers (three separate terminals)
uvicorn vendor_portal.server:app --port 8082   # required for Acts 2 & 3
uvicorn server.app:app --port 8080
cd dashboard && npm install && npm run dev
```

> **Acts 1 & 2** work out of the box — `agents/`, `auth/`, and `tools/` are
> symlinked to `baseline/` by default.
>
> **Act 3** requires switching to the Tenuo implementation:
> ```bash
> ./scripts/switch-mode.sh with-tenuo
> # then restart uvicorn server.app:app (port 8080)
> ```

Open http://localhost:3000

## Structure

```
baseline/               The app WITHOUT Tenuo
  agents/               LangGraph pipeline (6 agents, 3 levels)
  auth/                 4 standard auth layers (GCP SA, OAuth, SpiceDB, OPA)
  tools/                Tool definitions (invoice, vendor, payment)

with-tenuo/             Only the files that CHANGE to add Tenuo
  agents/               3 modified files (graph.py, invoice_processor.py, payment_executor.py)
  auth/                 3 new files (tenuo_local.py, tenuo_integration.py, tenuo_tool_node.py)
                        2 updated files (pipeline.py, tool_node.py — minor request ID tracking)

DIFF.md                 Exactly what changed and why
```

The server switches between baseline and with-tenuo when you run `switch-mode.sh` and restart. The dashboard UI does not trigger a mode switch on its own.

## The Demo

**Act 1 — The App:** Architecture overview. 3-level agent delegation, 4-layer auth stack.

**Act 2 — The Attack:** An invoice contains a fake bank change notice. The agent follows procedure and updates the vendor's bank. All 4 auth layers approve. Payment goes to the attacker.

**Act 3 — Tenuo:** Same attack. The warrant says `bank_account` must be `7291034851`. The agent tries `8847291034`. Denied.

See [DIFF.md](DIFF.md) for the exact code changes between baseline and with-tenuo.

## Modes

| Mode | `TENUO_MODE=` | What it does |
|------|---------------|-------------|
| Local SDK | `local` | Warrants issued locally. No cloud. |
| Tenuo Cloud | `cloud` | Triggers on [cloud.tenuo.ai](https://cloud.tenuo.ai). Receipt streaming. |

Cloud mode requires a Tenuo Cloud account and the following env vars in `.env`:

```
TENUO_CONTROL_PLANE_URL=https://api-staging.tenuo.ai
TENUO_API_KEY=<your key>
TENUO_AGENT_ID=<your agent id>
TENUO_SIGNING_KEY=<ed25519 hex>
TENUO_TRUSTED_ROOT=<issuer public key base64>
TENUO_WARRANT=<base64 warrant>
```

A trigger named `ap-invoice-batch-v7` must exist in the Tenuo Cloud control plane. Contact the Tenuo team for access. The demo works fully in `TENUO_MODE=local` without any of this.

## Links

- [Tenuo](https://tenuo.ai) — Cryptographic authorization for AI agents
- [Tenuo Core](https://github.com/tenuo-ai/tenuo) — Open source Rust kernel + Python SDK
- [Tenuo Cloud](https://cloud.tenuo.ai) — Control plane for warrant management
- [Early access](https://tenuo.ai/early-access.html)
