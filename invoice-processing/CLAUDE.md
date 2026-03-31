# CLAUDE.md — Tenuo Enterprise Demo

## Purpose

Enterprise sales demo for Tenuo Cloud. Three-act structure: (1) show AP automation working, (2) show 4 auth layers failing under attack, (3) show Tenuo stopping all attacks + Tenuo Cloud features.

## Structure

- `agents/` — LangGraph multi-agent AP automation (Python, Claude Haiku)
- `tools/` — Tool definitions backed by asyncpg
- `auth/` — Four auth layer implementations (GCP SA, OAuth, SpiceDB, OPA) + Tenuo
- `attacks/` — Three attack modes (compromised prompt, indirect injection, simulated)
- `vendor_portal/` — FastAPI mock vendor portal with injection payloads
- `dashboard/` — React dashboard (Vite + TypeScript + Tailwind)
- `server/` — FastAPI backend for SSE events + demo control API
- `db/` — PostgreSQL schema and seed data
- `opa/` — Rego policies
- `spicedb/` — Zanzibar schema and relationships

## Commands

```bash
make dev              # docker-compose up (postgres, spicedb, opa, portal)
make seed             # Seed database with fake data
make reset            # Wipe + re-seed all state
make run              # Run the LangGraph agents
make dashboard        # Start dashboard dev server
make test             # pytest
make lint             # ruff check + ruff format --check
make build            # Build all Docker images
make deploy           # Deploy to GCP
```

## Key Patterns

- LLM: Claude Haiku via `langchain-anthropic` (fast, cheap, injection-susceptible)
- Warrants stored as `warrant.to_base64()` in LangGraph state (checkpoint-safe)
- Keys in `KeyRegistry` (never serialized to state)
- Auth decisions logged to `auth_decisions` table AND streamed via SSE
- Tools are `@tool` decorated `langchain_core` tools
- Dashboard connects via SSE to `server/app.py`

## Dependencies

- `tenuo` SDK: install from `../tenuo/tenuo-python` in dev mode
- SpiceDB: real instance via `authzed` Python client
- OPA: real instance, REST API
- PostgreSQL 16 via `asyncpg`

## Testing

- `pytest tests/test_tools.py` — tool unit tests
- `pytest tests/test_auth_layers.py` — auth layer tests
- `pytest tests/test_graph.py` — graph execution tests
- `pytest tests/test_attacks.py` — attack mode verification

## Security

- Never commit real API keys or Tenuo Cloud credentials
- Injection payloads are for demo purposes only
- `.env` is gitignored
