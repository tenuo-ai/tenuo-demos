# Task-scoped Jira access for a triage agent on mcp-atlassian

The triage lead may read, comment on and move (to In Progress or Done) any
OPS issue. It hands a sub-agent one task: close out OPS-12. The sub-agent's
warrant is derived from the lead's and says exactly that: read OPS-12,
comment on it, move it to Done.

[mcp-atlassian](https://github.com/sooperset/mcp-atlassian) already lets you
pin a project (`JIRA_PROJECTS_FILTER`) and a tool list (`ENABLED_TOOLS`).
That's set once per server, so it can't tell this task from the next one: an
agent following an instruction planted in a ticket can still read the
security incident, close someone else's issue, or move OPS-12 to Won't Do.

## Run it

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv run main.py
```

```text
JIRA_PROJECTS_FILTER=OPS, ENABLED_TOOLS=jira_get_issue,jira_add_comment,jira_transition_issue:
  read OPS-12                      reached Jira
  comment on OPS-12                reached Jira
  move OPS-12 to Done              reached Jira
  read OPS-99 (security incident)  reached Jira
  comment on OPS-40                reached Jira
  move OPS-40 to Done              reached Jira
  move OPS-12 to Won't Do          reached Jira

same + Tenuo (the agent's warrant: read, comment on and close OPS-12):
  read OPS-12                      reached Jira
  comment on OPS-12                reached Jira
  move OPS-12 to Done              reached Jira
  read OPS-99 (security incident)  REFUSED  Constraint 'issue_key'
  comment on OPS-40                REFUSED  Constraint 'issue_key'
  move OPS-40 to Done              REFUSED  Constraint 'issue_key'
  move OPS-12 to Won't Do          REFUSED  Constraint 'transition_id'

Jira received these writes:
  POST /rest/api/2/issue/OPS-12/comment {"body": "Fixed in 4.2.1, closing."}
  POST /rest/api/2/issue/OPS-12/transitions {"transition": {"id": "31"}}
```

Both runs are the released `mcp-atlassian` over stdio. `fake_jira.py` stands
in for the Jira REST API and records every request, so nothing touches a real
Jira.

## What changes in the server

`tenuo_atlassian.py` runs the stock CLI with one addition: a Tenuo middleware
at the front of the server's FastMCP middleware list.

```python
verifier = MCPVerifier(authorizer=Authorizer(trusted_roots=[root]), require_warrant=True)
main_mcp.middleware.insert(0, TenuoMiddleware(verifier))
```

Every call must carry a warrant chain in `_meta.tenuo` that leads back to the
trusted key, plus a signature from the key the warrant names. The check is
per argument and closed-world: `issue_key` and `transition_id` must fit, and
an argument the warrant doesn't name (`fields`, `comment` on a transition) is
refused. Refused calls never run the tool, so they never reach Jira.

The agent's warrant can only be narrower than the lead's: the lead can't hand
out HR issues or Won't Do, and the agent can't pass on OPS-40.

## Where the warrant comes from

The agent's side holds a key and attaches `_meta.tenuo`; `tenuo_meta()` in
`main.py` shows the format. Agents built with a Tenuo integration (OpenAI
Agents, LangChain's MCP adapter, `tenuo.mcp.SecureMCPClient`, Temporal) do
this for you. Callers without a warrant are refused when the check is on, so
it's for servers serving agents you run.

## Tests

```bash
uv run pytest
```

- the server's own scoping alone lets every call through (the baseline)
- with Tenuo, Jira receives exactly the two task writes, OPS-99 is never fetched, and each refusal names the argument that failed
- no warrant, an untrusted root, a stolen warrant without its key, and a child warrant without its parent never reach Jira
- the lead can't delegate outside its scope; the agent can't re-delegate wider

Tested with mcp-atlassian 0.23.1, tenuo 0.3.2 and mcp 1.30.
