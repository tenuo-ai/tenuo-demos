# Per-call authority for any MCP server behind mcp-proxy

[mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) puts a local stdio MCP
server on the network. Whoever can reach it (or holds its bearer token) can
call every tool with any arguments.

Here a CI agent was asked to update the docs. Its warrant says: read under
`docs/`, write `docs/notes.md`. It's handed down from a coordinator that may
write anywhere in `docs/`. The agent then also tries what a prompt-injected
agent would.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and Node (`npx`, for the reference
filesystem server).

```bash
uv run main.py
```

```text
stock mcp-proxy (anyone who can reach it, or holds its bearer token):
  read the guide           ran
  write docs/notes.md      ran
  overwrite CI workflow    ran
  read ../.env             ran
  move the guide           ran
  -> ci.yml OVERWRITTEN, guide.md moved

mcp-proxy + Tenuo (the agent's warrant: read docs/, write docs/notes.md):
  read the guide           ran
  write docs/notes.md      ran
  overwrite CI workflow    REFUSED  Tenuo denied write_file: Constraint 'path' not satisfied
  read ../.env             REFUSED  Tenuo denied read_text_file: Constraint 'path' not satisfied
  move the guide           REFUSED  Tenuo denied move_file: Tool 'move_file' is not authorized
  -> ci.yml untouched, guide.md in place
```

Both runs use the real `mcp-proxy` CLI over streamable HTTP and the real
`@modelcontextprotocol/server-filesystem`. Its own allowed directory is the
whole project, so the stock run is what that server permits.

## What changes in the proxy

`tenuo_mcp_proxy.py` runs the stock CLI with one change: the proxy's
`tools/call` handler checks the call first. Every call must carry a warrant
chain in `_meta.tenuo` that leads back to one trusted public key, plus a
signature from the key the warrant names. Allowed calls are forwarded with
the warrant stripped; everything else is answered by the proxy and never
reaches the server behind it.

Because the check sits in the proxy, it works for any stdio server you put
behind it, unchanged. Paths are checked with `Subpath`, which normalizes `..`
before comparing. The agent's warrant is derived from the coordinator's, so
it can only be narrower: the agent can't write `docs/other.md` even though
its coordinator could, and it can't hand anyone more than it holds.

## Where the warrant comes from

The caller's side: an agent built with a Tenuo integration (OpenAI Agents,
LangChain's MCP adapter, `tenuo.mcp.SecureMCPClient`, Temporal) holds a key
and attaches `_meta.tenuo`; `tenuo_meta()` in `main.py` shows the format.
Callers that don't send one are refused, so this is for proxies serving
agents you run.

## Tests

```bash
uv run pytest
```

- the stock proxy lets every call through (the baseline)
- with Tenuo: the two task calls run once; overwriting CI, reading `../.env`, moving files and writing outside the agent's narrower grant don't happen
- no warrant, a warrant from an untrusted root, and a stolen warrant used without its key are refused
- the agent can't re-delegate a wider path

Tested with mcp-proxy 0.13.0, mcp 1.30, tenuo 0.3.2 and server-filesystem 1.0.0.
