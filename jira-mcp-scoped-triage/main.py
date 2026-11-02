"""A triage agent on mcp-atlassian: the server's own scoping vs a task warrant.

The triage lead may read, comment on and move (to In Progress or Done) any
OPS issue. It hands one task to a sub-agent: close out OPS-12. The sub-agent
gets a warrant for exactly that, derived from the lead's: read OPS-12,
comment on it, move it to Done.

The sub-agent then also does what an injected instruction in a ticket would
ask. The server's own controls, scoped as tightly as they go (one project,
three tools), let all of it through. With the Tenuo check, only the task
reaches Jira.

Runs offline: fake_jira stands in for the Jira REST API.
"""

import asyncio
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tenuo import Exact, OneOf, Regex, SigningKey, Warrant, Wildcard, encode_warrant_stack

HERE = Path(__file__).parent
IN_PROGRESS, DONE, WONT_DO = "21", "31", "41"

org_key = SigningKey.generate()  # the operator's trust root; the server trusts only this
lead_key = SigningKey.generate()
agent_key = SigningKey.generate()

OPS_ISSUE = Regex(r"^OPS-\d+$")

lead_warrant = (
    Warrant.mint_builder()
    .capability("jira_get_issue", {"issue_key": OPS_ISSUE})
    .capability("jira_add_comment", {"issue_key": OPS_ISSUE, "body": Wildcard()})
    .capability("jira_transition_issue", {"issue_key": OPS_ISSUE, "transition_id": OneOf([IN_PROGRESS, DONE])})
    .holder(lead_key.public_key)
    .ttl(3600)
    .mint(org_key)
)


def agent_warrant_for(issue_key: str, transition_id: str) -> Warrant:
    """One issue, one transition. Tenuo rejects anything wider than the lead's warrant."""
    return (
        lead_warrant.grant_builder()
        .capability("jira_get_issue", {"issue_key": Exact(issue_key)})
        .capability("jira_add_comment", {"issue_key": Exact(issue_key), "body": Wildcard()})
        .capability("jira_transition_issue", {"issue_key": Exact(issue_key), "transition_id": Exact(transition_id)})
        .holder(agent_key.public_key)
        .ttl(900)
        .grant(lead_key)
    )


def tenuo_meta(chain: list[Warrant], key: SigningKey, tool: str, args: dict) -> dict:
    proof = chain[-1].sign(key, tool, args, int(time.time()))
    warrant = chain[0].to_base64() if len(chain) == 1 else encode_warrant_stack(chain)
    return {"tenuo": {"warrant": warrant, "signature": base64.b64encode(bytes(proof)).decode()}}


# (label, tool, args)
AGENT_CALLS = [
    ("read OPS-12", "jira_get_issue", {"issue_key": "OPS-12"}),
    ("comment on OPS-12", "jira_add_comment", {"issue_key": "OPS-12", "body": "Fixed in 4.2.1, closing."}),
    ("move OPS-12 to Done", "jira_transition_issue", {"issue_key": "OPS-12", "transition_id": DONE}),
    ("read OPS-99 (security incident)", "jira_get_issue", {"issue_key": "OPS-99"}),
    ("comment on OPS-40", "jira_add_comment", {"issue_key": "OPS-40", "body": "Duplicate, closing."}),
    ("move OPS-40 to Done", "jira_transition_issue", {"issue_key": "OPS-40", "transition_id": DONE}),
    ("move OPS-12 to Won't Do", "jira_transition_issue", {"issue_key": "OPS-12", "transition_id": WONT_DO}),
]

# The server's own scoping, as tight as it goes for this task.
NATIVE_SCOPE = {
    "JIRA_PROJECTS_FILTER": "OPS",
    "ENABLED_TOOLS": "jira_get_issue,jira_add_comment,jira_transition_issue",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def run(with_tenuo: bool, calls=AGENT_CALLS, chain=None, key=None, attach=True):
    """Run calls against the server; returns (label, reached_jira, is_error, text) and the Jira request log."""
    chain = chain or [lead_warrant, agent_warrant_for("OPS-12", DONE)]
    key = key or agent_key
    log = Path(tempfile.mkstemp()[1])
    port = _free_port()
    jira = subprocess.Popen([sys.executable, str(HERE / "fake_jira.py"), str(port)], env={**os.environ, "JIRA_LOG": str(log)})
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "JIRA_URL": f"http://127.0.0.1:{port}",
        "JIRA_PERSONAL_TOKEN": "fake",
        **NATIVE_SCOPE,
    }
    if with_tenuo:
        env["TENUO_TRUSTED_ROOT"] = bytes(org_key.public_key.to_bytes()).hex()
        params = StdioServerParameters(command=sys.executable, args=[str(HERE / "tenuo_atlassian.py")], env=env)
    else:
        params = StdioServerParameters(command=str(Path(sys.executable).parent / "mcp-atlassian"), args=[], env=env)
    results = []
    try:
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for label, tool, args in calls:
                    before = log.read_text().count("\n")
                    meta = tenuo_meta(chain, key, tool, args) if attach else None
                    res = await session.call_tool(tool, args, meta=meta)
                    new = log.read_text().splitlines()[before:]
                    reached = any(f"/issue/{args['issue_key']}" in line for line in new)
                    text = "".join(getattr(b, "text", "") for b in res.content)
                    results.append((label, reached, res.isError, text))
    finally:
        jira.kill()
    return results, log.read_text().splitlines()


def jira_writes(log: list[str]) -> list[str]:
    return [line for line in log if not line.startswith("GET")]


def report(title: str, results) -> None:
    print(f"\n{title}")
    for label, reached, _, text in results:
        if reached:
            print(f"  {label:32} reached Jira")
        else:
            print(f"  {label:32} REFUSED  {text.split(' not satisfied')[0][:60]}")


def main() -> None:
    scope = ", ".join(f"{k}={v}" for k, v in NATIVE_SCOPE.items())
    results, _ = asyncio.run(run(with_tenuo=False))
    report(f"{scope}:", results)
    results, log = asyncio.run(run(with_tenuo=True))
    report("same + Tenuo (the agent's warrant: read, comment on and close OPS-12):", results)
    print("\nJira received these writes:")
    for line in jira_writes(log):
        print(f"  {line}")


if __name__ == "__main__":
    main()
