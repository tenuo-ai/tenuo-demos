# Tenuo + FastMCP Integration Demo


## Architecture Overview

```
                           The stack today
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  Agent (k8s Job)                                                 │
  │  ┌────────────────────┐                                          │
  │  │ PermissionSet      │  OAuth token                             │
  │  │ (READ, WRITE, …)   │──────────┐                              │
  │  │ AgentIdentity      │          │                               │
  │  └────────────────────┘          ▼                               │
  │                         ┌─────────────────┐    tools/call        │
  │                         │ RemoteMCPClient  │──────────────────┐  │
  │                         └─────────────────┘                   │  │
  │                                                               ▼  │
  │                         ┌─────────────────────────────────────┐  │
  │                         │ task-mcp-resource  (FastMCP)        │  │
  │                         │                                     │  │
  │                         │   OAuth / introspection             │  │
  │                         │          │                          │  │
  │                         │          ▼                          │  │
  │                         │   ┌──────────────┐                  │  │
  │  THE GAP ─────────────► │   │  (no tool-   │  Flat scope:    │  │
  │                         │   │   level       │  ["read"]       │  │
  │                         │   │   enforcement)│                  │  │
  │                         │   └──────┬───────┘                  │  │
  │                         │          ▼                          │  │
  │                         │   Tool handler runs                 │  │
  │                         └─────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────┘

                        With Tenuo warrant middleware
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  Agent (k8s Job)                                                 │
  │  ┌────────────────────┐                                          │
  │  │ PermissionSet      │  OAuth token + warrant in _meta          │
  │  │ AgentIdentity      │──────────┐                               │
  │  └────────────────────┘          │                               │
  │                         ┌────────▼────────┐   tools/call         │
  │                         │ RemoteMCPClient  │──────────────────┐  │
  │                         │ (adds _meta with │                  │  │
  │                         │  warrant + PoP)  │                  │  │
  │                         └─────────────────┘                   │  │
  │                                                               ▼  │
  │                         ┌─────────────────────────────────────┐  │
  │                         │ task-mcp-resource  (FastMCP)        │  │
  │                         │                                     │  │
  │                         │   OAuth / introspection             │  │
  │                         │          │                          │  │
  │                         │          ▼                          │  │
  │                         │   ┌──────────────────────────┐      │  │
  │                         │   │ TenuoMiddleware           │      │  │
  │  CLOSED ────────────►   │   │  • verify warrant chain  │      │  │
  │                         │   │  • check PoP signature   │      │  │
  │                         │   │  • enforce tool + args   │      │  │
  │                         │   │  • strip _meta.tenuo     │      │  │
  │                         │   └──────────┬───────────────┘      │  │
  │                         │          allowed?                   │  │
  │                         │        ╱         ╲                  │  │
  │                         │      YES          NO                │  │
  │                         │       │            │                │  │
  │                         │       ▼            ▼                │  │
  │                         │   Tool runs    isError + deny msg   │  │
  │                         └─────────────────────────────────────┘  │
  └──────────────────────────────────────────────────────────────────┘

                        Delegation chain (stretch goal)
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │   Issuer (control plane)                                         │
  │      │                                                           │
  │      │ mint root warrant                                         │
  │      │  tools: [get_tasks, search_tasks, create_task, ...]       │
  │      ▼                                                           │
  │   Orchestrator agent                                             │
  │      │                                                           │
  │      │ attenuate (narrow)                                        │
  │      │  tools: [get_tasks, search_tasks]   ← read-only subset   │
  │      ▼                                                           │
  │   Worker agent (k8s Job)                                         │
  │      │                                                           │
  │      │ uses narrowed warrant to call MCP server                  │
  │      ▼                                                           │
  │   task-mcp-resource verifies full chain                          │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

```bash
pip install "tenuo[fastmcp]"
```

This installs `tenuo`, `mcp`, and `fastmcp>=3.2.1`.

---

## Step 1: Generate keys

One issuer key for the demo. In production this lives in a secret store.

```python
from tenuo import SigningKey

# The issuer (control plane) key — mints warrants
issuer_key = SigningKey.generate()
print("Issuer public key (hex):", issuer_key.public_key.to_hex())

# The agent's key — proves holder identity via PoP signatures
agent_key = SigningKey.generate()
print("Agent public key (hex):", agent_key.public_key.to_hex())
```

---

## Step 2: Set up the MCP server with TenuoMiddleware



```python
# server.py
from fastmcp import FastMCP
from tenuo import Authorizer, PublicKey
from tenuo.mcp import MCPVerifier, TenuoMiddleware

ISSUER_PUB_HEX = "..."  # from step 1

# --- Tenuo setup (once at startup) ---
authorizer = Authorizer(
    trusted_roots=[PublicKey.from_hex(ISSUER_PUB_HEX)]
)
verifier = MCPVerifier(authorizer=authorizer)

# --- FastMCP app with Tenuo middleware ---
mcp = FastMCP(
    "task-mcp-resource",
    middleware=[
        # Existing: OAuth / introspection middleware
        # ...
        # New: warrant enforcement — sits after auth, before tools
        TenuoMiddleware(verifier),
    ],
)


# --- Read tools ---
@mcp.tool()
async def get_tasks(project: str) -> str:
    return f"Tasks for {project}: [task-1, task-2, task-3]"


@mcp.tool()
async def search_tasks(query: str) -> str:
    return f"Search results for '{query}': [task-2]"


@mcp.tool()
async def get_wiki_page(slug: str) -> str:
    return f"Wiki page: {slug}"


@mcp.tool()
async def list_articles(category: str = "all") -> str:
    return f"Articles in '{category}': [article-1, article-2]"


# --- Write tools ---
@mcp.tool()
async def create_task(title: str, project: str) -> str:
    return f"Created task '{title}' in {project}"


@mcp.tool()
async def update_task(task_id: str, status: str) -> str:
    return f"Updated {task_id} → {status}"


@mcp.tool()
async def delete_task(task_id: str) -> str:
    return f"Deleted {task_id}"
```

The middleware runs `MCPVerifier.verify` on every `tools/call`. If the
request has no `_meta.tenuo` or the warrant doesn't cover the tool, the
call is **denied** with a structured `isError` result. The tool handler
**never runs**.

---

## Step 3: Mint a read-only warrant

```python
# mint_warrant.py
from tenuo import SigningKey, Warrant, Capability, Pattern

issuer_key = SigningKey.from_hex("...")  # from step 1
agent_key = SigningKey.from_hex("...")   # agent's key

# Read-only warrant: only these four tools, 1 hour TTL
read_warrant = (
    Warrant.mint_builder()
    .capability("get_tasks")
    .capability("search_tasks")
    .capability("get_wiki_page")
    .capability("list_articles")
    .holder(agent_key.public_key)
    .ttl(3600)
    .mint(issuer_key)
)

print("Warrant minted, tools:", [c.action for c in read_warrant.capabilities])
```

---

## Step 4: Call with a warrant (allowed)

The agent signs a Proof-of-Possession per call and sends the warrant
in `params._meta.tenuo`. For a root warrant (minted directly by a
trusted issuer, depth 0), a single-warrant encoding is sufficient —
the server can verify the issuer against its trust anchors in one step.

```python
# client_demo.py
import asyncio, time, base64
from tenuo import SigningKey
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

agent_key = SigningKey.from_hex("...")
read_warrant = ...  # from step 3


async def call_with_warrant(tool_name: str, arguments: dict) -> str:
    """Call an MCP tool with a Tenuo warrant in _meta."""
    # PoP signature: proves the caller holds the warrant's private key
    timestamp = int(time.time())
    pop = read_warrant.sign(agent_key, tool_name, arguments, timestamp=timestamp)

    # Wire format: single warrant + PoP travel in _meta.tenuo.
    # This works for root warrants (depth 0, issuer = trusted root).
    # For delegation chains see Step 7 — use WarrantStack encoding.
    meta = {
        "tenuo": {
            "warrant": read_warrant.to_base64(),
            "signature": base64.b64encode(bytes(pop)).decode(),
        }
    }

    server_params = StdioServerParameters(command="python", args=["server.py"])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments, meta=meta)
            return result


async def main():
    # --- Allowed: read tools ---
    print("=== get_tasks (should PASS) ===")
    r = await call_with_warrant("get_tasks", {"project": "demo"})
    print(r)

    print("\n=== search_tasks (should PASS) ===")
    r = await call_with_warrant("search_tasks", {"query": "urgent"})
    print(r)


asyncio.run(main())
```

Expected: both calls succeed — the warrant covers `get_tasks` and
`search_tasks`.

---

## Step 5: Scope break — write tool denied

Same warrant, call a write tool:

```python
async def scope_break():
    print("=== create_task (should DENY) ===")
    r = await call_with_warrant(
        "create_task",
        {"title": "hacked task", "project": "demo"},
    )
    print(r)
    # → isError: true
    # → "Authorization denied: tool 'create_task' not in warrant capabilities"
```

The server **rejects** the call. The tool handler **never executes**.
Same OAuth token, different tool — blocked at the MCP boundary.

---

## Step 6: (Optional) Mint a constrained write warrant

```python
write_warrant = (
    Warrant.mint_builder()
    .capability("create_task", project=Pattern("demo-*"))
    .holder(agent_key.public_key)
    .ttl(600)  # 10 min
    .mint(issuer_key)
)
```

- `create_task(title="x", project="demo-app")` → **allowed**
- `create_task(title="x", project="production")` → **denied** (Pattern
  mismatch)
- `delete_task(task_id="1")` → **denied** (not in capabilities)

---