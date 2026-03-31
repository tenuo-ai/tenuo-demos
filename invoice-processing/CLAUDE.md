# CLAUDE.md — Tenuo Enterprise Demo

## Purpose

Demo of the AP automation use case for Tenuo. Three-act structure: (1) show AP automation working, (2) show 4 auth layers failing under attack, (3) show Tenuo stopping all attacks + Tenuo Cloud features.

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
docker compose up -d postgres opa  # Start only the required local services
                                    # (make dev starts ALL services including
                                    #  tenuo-authorizer which needs TENUO_API_KEY)
make seed             # Seed database with fake data
make reset            # Wipe + re-seed all state
make run              # Run the LangGraph agents
make dashboard        # Start dashboard dev server
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

## Auth Layers — What's Real vs. Simulated

| Layer | Implementation | Real service? |
|-------|---------------|---------------|
| GCP SA | Static dict in `auth/gcp_sa.py` | No — simulated in-memory |
| OAuth | Static dict in `auth/oauth.py` | No — simulated in-memory |
| SpiceDB | In-memory fallback in `auth/spicedb.py` | No — simulated in-memory |
| OPA | HTTP call to `localhost:8181` | Yes — needs `docker compose up -d opa` |
| Tenuo | Local SDK or Tenuo Cloud | No credentials needed for local mode |

Only Postgres and OPA need to be running locally.

## Dependencies

- `tenuo[langchain]` SDK: declared in `pyproject.toml`; installed via `uv pip install -e ".[dev]"`
- SpiceDB: uses real `authzed` gRPC client when `SPICEDB_ENDPOINT` is set, falls back to in-memory (demo only runs postgres + OPA)
- OPA: real instance, REST API
- PostgreSQL 16 via `asyncpg`

## Testing

No automated tests. Run the demo manually — the three acts are the test.

## Security

- Never commit real API keys or Tenuo Cloud credentials
- Injection payloads are for demo purposes only
- `.env` is gitignored
