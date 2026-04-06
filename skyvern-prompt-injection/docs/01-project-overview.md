# Project Overview: Tenuo + Skyvern

This document summarizes the three projects that form the foundation of these end-to-end tutorials.

---

## Tenuo Core

**Language:** Rust | **Bindings:** Python (PyO3) | **Path:** `tenuo/tenuo-core/`

Tenuo Core is a cryptographic authorization library for AI agents. Its core primitive is the **Warrant** — a capability token that controls what tools an agent can call, under what constraints, and for how long.

### Key Concepts

- **Warrant**: A signed capability token (`tnu_wrt_` prefixed) containing:
  - Capabilities: map of tool name to constraints
  - Holder: bound to a specific agent's public key
  - TTL: expires naturally (default 5 min, max 90 days)
  - Depth: delegation level in a chain (0 = root)
  - Clearance: hierarchical authority level (Untrusted=0 through System=50)

- **Constraints** (13+ types): Exact, Pattern, Regex, OneOf, Range, CIDR, Subpath, UrlSafe, Shlex, CEL expressions, and logical combinators (All, Any, Not)

- **Monotonic Attenuation**: Delegated authority can only shrink, never expand. A parent warrant for `send_email to *` can delegate `send_email to *@company.com`, but not the reverse.

- **Proof-of-Possession (PoP)**: Warrants are bound to a holder's public key. To use a warrant, the holder must sign a challenge with their private key. Stolen tokens are useless without the key.

- **Signed Receipts**: Cryptographic proof of what an agent did, when, and under what authority.

### Architecture: Control Plane vs Data Plane

| | Control Plane | Data Plane |
|---|---|---|
| **Role** | Issues authority | Verifies authority |
| **Keys** | Holds private keys | Holds only public keys |
| **Operations** | Issue warrants, manage approvals, revocation lists | Verify warrants offline (~27μs) |
| **Deployment** | Central server | In-process, sidecar, or gateway |

### Delegation Chain

```
Root Warrant (Control Plane) → Orchestrator Warrant → Worker Warrant
      depth=0                       depth=1                depth=2
   signed by CP                 signed by Orch         signed by Worker
```

Verification checks at each hop:
1. Child.parent_id == Parent.id
2. Child.depth == Parent.depth + 1
3. Child.expires_at <= Parent.expires_at
4. Child.constraints subset of Parent.constraints
5. All signatures valid (Ed25519)

### Integration APIs

Tenuo Core provides Python bindings and integrations for:
- **Direct Python**: `@guard(tool="...")` decorator, `mint_sync()` context manager
- **OpenAI**: `GuardBuilder` wrapping OpenAI client
- **LangChain / LangGraph**: `guard_tools()`, `TenuoToolNode`
- **MCP**: `SecureMCPClient`, `MCPVerifier`
- **FastAPI**: `TenuoGuard` dependency

---

## Tenuo Cloud

**Language:** Go 1.24 (server) + TypeScript/Next.js 14 (dashboard) | **Path:** `tenuo-cloud/`

Tenuo Cloud is the control plane backend that operationalizes Tenuo Core at scale. It handles warrant issuance, key management, revocation, audit, and administration.

### Core Services

| Category | Services |
|----------|----------|
| **Warrant Pipeline** | AgentService, TriggerService, FireService, IssuanceService |
| **Key Management** | KeyService (GCP KMS + in-memory), Ed25519 signing |
| **Revocation** | RevocationService, Signed Revocation Lists (SRL) |
| **Approvals** | ApprovalService — multi-level, M-of-N threshold |
| **Audit** | AuditIngestService, ReceiptService, IntegrityService |
| **Discovery** | TemplateService, RecommendationService, ObservationService |
| **Admin** | TenantService, UserService, APIKeyService, WebhookService |

### Warrant Issuance Flow (Trigger Fire)

1. Admin creates a **Trigger** — maps a business event to a warrant specification
2. Agent fires trigger via `POST /v1/triggers/{id}/fire`
3. FireService resolves constraints from event data
4. KMS signs warrant with tenant's root key
5. Warrant logged in issuance_log for audit
6. Warrant returned to agent

### Helios Dashboard (Next.js)

Admin UI for: receipts, warrants, keys, agents, triggers, templates, recommendations, approvals, audit logs, and authorizer fleet health.

### Infrastructure

- **Database:** PostgreSQL 15+ with row-level security for tenant isolation
- **KMS:** GCP Cloud KMS (HSM support) with in-memory fallback
- **Cache:** Redis (distributed) or in-memory
- **Deployment:** Distroless Docker image, Helm chart for GKE
- **Auth:** API keys (`tc_...` prefix) with scopes: admin, authorizer, read-only

---

## Skyvern

**Language:** Python 3.11+ | **Framework:** FastAPI + Playwright | **Path:** `skyvern/`

Skyvern is an AI-powered browser automation platform that uses LLMs and computer vision instead of brittle CSS/XPath selectors. It works on previously unseen websites without custom code.

### Execution Flow

```
API Request
  → WorkflowService.execute_workflow()
    → Block execution loop (25+ block types)
      → ForgeAgent: scrape page → LLM plans actions → execute via Playwright → LLM verifies goal
        → Result extraction & webhook callback
```

### Core Components

**ForgeAgent** (`forge/agent.py`, 9300 lines):
- Multi-agent LLM pipeline: Comprehension → Planner → Actor → Validator
- Speculative execution — plans next step before current completes
- Action caching for 10-100x speedup on repeated tasks

**Scraper** (`webeye/scraper/`):
- JavaScript injection extracts DOM into element tree with CSS selectors
- Screenshots annotated for vision LLM consumption
- Incremental scraping tracks DOM changes between steps

**Action Handler** (`webeye/actions/handler.py`):
- 15+ action types: Click, InputText, SelectOption, Upload, Download, SolveCaptcha, etc.
- Recursive iframe resolution
- Post-action screenshot comparison for verification

**Workflow Engine** (`forge/sdk/workflow/`):
- 25+ block types: TaskBlock, CodeBlock, ForLoopBlock, ConditionalBlock, HttpRequestBlock, SendEmailBlock, etc.
- Jinja2 templating with sandboxed environment
- Script generation and caching for CodeBlock execution
- Parameter system: workflow params, context params, secrets (Bitwarden, 1Password, Azure Vault)

**LLM Layer** (`forge/sdk/api/llm/`):
- 50+ model configs via LiteLLM abstraction
- Supports: OpenAI, Anthropic, Azure, Bedrock, Gemini, Ollama, OpenRouter, Groq
- Separate handlers for: primary actions, extraction, goal verification, script generation

### Key APIs

```
POST /v1/run/tasks       — Run a single task (prompt + URL)
POST /v1/workflows       — Create a workflow
POST /v1/workflows/run   — Execute a workflow
GET  /v1/runs/{id}       — Check run status
```

### Deployment

- **Quick start:** `pip install skyvern && skyvern quickstart`
- **Docker:** PostgreSQL + Skyvern server + Skyvern UI + optional Vaultwarden
- **Config:** SQLite default for local dev, PostgreSQL for production
- **Browser:** Chromium via Playwright (headful or headless)

---

## Integration Surface: How They Connect

The natural integration point between Tenuo and Skyvern is through **tenuo-core's Python bindings (PyO3)** into Skyvern's Python codebase.

### Where Warrants Can Be Enforced

| Integration Point | Location | What It Controls |
|---|---|---|
| **Action handler** | `webeye/actions/handler.py` | Verify warrant before each browser action (click, navigate, input) |
| **Workflow blocks** | `forge/sdk/workflow/models/block.py` | Gate block execution on valid warrant with matching capabilities |
| **HTTP requests** | `HttpRequestBlock` | Require warrants with URL constraints for external API calls |
| **MCP tools** | `cli/mcp_tools/` | Warrant-gate Skyvern's MCP tool surface |
| **Task creation** | `forge/sdk/routes/sdk.py` | Require warrant at task submission with URL/action scope |

### Example Flow

```
1. Tenuo Cloud issues warrant to Skyvern agent:
   - Tool: "browser_navigate", Constraint: url = UrlPattern("https://*.gov/*")
   - Tool: "browser_extract", Constraint: fields = OneOf(["name", "address", "status"])
   - TTL: 10 minutes
   - Holder: agent's Ed25519 public key

2. Skyvern agent receives warrant + attenuates for specific task

3. At each action boundary, Tenuo authorizer verifies:
   - Warrant signature chain is valid
   - PoP matches holder's key
   - Action constraints are satisfied (URL matches, fields allowed)
   - Warrant hasn't expired or been revoked

4. Signed receipts record every authorized action for audit
```
