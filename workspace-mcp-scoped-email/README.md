# Task-scoped email for agents calling Workspace MCP

Your support coordinator may email anyone at acme.com. It asks a drafting
sub-agent to reply to Bob on one thread. Should that sub-agent be able to
email anyone at acme.com? Bcc someone? Forward a different message?

Here it can do exactly one thing: send to bob@acme.com on thread-4471. The
[Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp) server
checks that on every call, so it holds even if the agent is talked into
something else.

```text
coordinator   send_gmail_message(to = *@acme.com)
   |
   | delegates one task
   v
drafter       send_gmail_message(to == bob@acme.com, thread_id == thread-4471)
   |
   | tools/call + warrant chain + signature
   v
Workspace MCP verifies, then calls Gmail
```

## Run it

```bash
uv run main.py
```

```text
  drafter -> send_gmail_message: reply to Bob             ALLOWED
  drafter -> send_gmail_message: forward outside          DENIED   Constraint 'to' not satisfied
  drafter -> send_gmail_message: add a Bcc                DENIED   Constraint 'bcc' not satisfied: unknown field not allowed
  drafter -> send_gmail_message: forward another message  DENIED   Constraint 'forward_message_id' not satisfied: unknown field not allowed

emails sent: [{'To': 'bob@acme.com', 'Subject': 'Re: INV-4471'}]
```

No Google account needed: `fake_google.py` replaces only the Gmail API client.
The MCP server, its middleware and the real `send_gmail_message` code all run
as shipped; the recipients printed above are read back from the MIME message
the tool built.

## What changes on the server

`server.py` is the whole change: one `TenuoMiddleware`, trusting one public
key (the operator's), installed first so it checks the arguments exactly as
the client signed them. Every `tools/call` must carry a warrant chain that
leads back to that key and a signature from the key the warrant names. A call
without one is refused before Google is touched.

Workspace MCP's own controls (`--read-only`, `--permissions`, tool tiers)
decide which tools exist. OAuth decides whose mailbox. The warrant decides
what this agent may do with that tool for this task, per argument.

The check is closed-world: an argument the warrant doesn't name is refused,
so `bcc`, `attachments`, `forward_message_id`, `reply_all` and `from_email`
are all off unless a warrant grants them. Use the schema's argument names in
warrants; camelCase spellings are refused rather than renamed past the check.

## Where the warrant comes from

The client side: an agent built with a Tenuo integration (OpenAI Agents,
LangChain's MCP adapter, `tenuo.mcp.SecureMCPClient`, Temporal) holds a key
and attaches `_meta.tenuo` to each call. `tenuo_meta()` in `main.py` shows
the wire format. Hosts that don't attach warrants (Claude Desktop, Cursor)
are refused by this server; it's meant for deployments where you run the
agents.

## Tests

```bash
uv run pytest
```

- the scoped reply is sent once; nothing else goes out
- another thread, no warrant, a stolen warrant used without the holder key, a delegated warrant without its parent, and a warrant from an untrusted root are refused
- a camelCase alias can't smuggle in an argument
- the coordinator can't delegate outside acme.com; the drafter can't re-delegate a wider recipient

Tested with workspace-mcp 2.1.0, fastmcp 4.1.0 and tenuo 0.3.2.
