# Invoice Processing Demo

A multi-agent pipeline that processes invoices, verifies vendors, and executes payments. Built on [LangGraph](https://github.com/langchain-ai/langgraph).

This demo shows a prompt injection that redirects a $14,200 payment to the wrong bank account — through four layers of properly configured authorization. Then shows how [Tenuo](https://tenuo.ai) blocks it.

## Quick Start

```bash
cd invoice-processing

# 1. Set up
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start infrastructure
docker compose up -d postgres opa

# 3. Choose mode and start
./scripts/switch-mode.sh baseline   # Without Tenuo (Acts 1 & 2)
# or
./scripts/switch-mode.sh with-tenuo # With Tenuo (Act 3)

# 4. Seed and run
python -m db.seed
uvicorn vendor_portal.server:app --port 8082 &
uvicorn server.app:app --port 8080 &
cd dashboard && npm install && npm run dev
```

Open http://localhost:3000

## Structure

```
baseline/               The app WITHOUT Tenuo
  agents/               LangGraph pipeline (6 agents, 3 levels)
  auth/                 4 standard auth layers (GCP SA, OAuth, SpiceDB, OPA)
  tools/                Tool definitions (invoice, vendor, payment)

with-tenuo/             Only the files that CHANGE to add Tenuo
  agents/               3 modified files (graph.py, invoice_processor, payment_executor)
  auth/                 3 new files (tenuo_local.py, tenuo_integration.py, tenuo_tool_node.py)

DIFF.md                 Exactly what changed and why
```

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

## Links

- [Tenuo](https://tenuo.ai) — Cryptographic authorization for AI agents
- [Tenuo Core](https://github.com/tenuo-ai/tenuo) — Open source Rust kernel + Python SDK
- [Tenuo Cloud](https://cloud.tenuo.ai) — Control plane for warrant management
- [Early access](https://tenuo.ai/early-access.html)
