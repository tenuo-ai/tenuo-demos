"""The same agent calls, through stock mcp-proxy and through mcp-proxy with Tenuo.

mcp-proxy exposes the reference filesystem MCP server over HTTP. A CI agent
was asked to update the docs. Its coordinator holds a warrant to read and
write under docs/; it hands the agent a narrower one: read docs/, write only
docs/notes.md.

Then the agent (scripted, as if prompt-injected) also tries to overwrite the
CI workflow, read .env through a ../ path, and move files around. The
filesystem server's own allowed directory is the whole project, so stock
mcp-proxy lets all of it through. With Tenuo in the proxy, only the task's
two calls reach the server.

Needs Node (npx) for the filesystem server.
"""

import asyncio
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tenuo import Exact, SigningKey, Subpath, Warrant, Wildcard, encode_warrant_stack

FILESYSTEM_SERVER = ["npx", "-y", "@modelcontextprotocol/server-filesystem@1.0.0"]
HERE = Path(__file__).parent

org_key = SigningKey.generate()  # the proxy trusts only this key
coordinator_key = SigningKey.generate()
agent_key = SigningKey.generate()


def make_project() -> Path:
    work = Path(tempfile.mkdtemp(prefix="project-")).resolve()
    (work / "docs").mkdir()
    (work / ".github/workflows").mkdir(parents=True)
    (work / "docs/guide.md").write_text("# Guide\n")
    (work / ".github/workflows/ci.yml").write_text("on: push\n")
    (work / ".env").write_text("DEPLOY_TOKEN=s3cret\n")
    return work


def warrants(work: Path) -> list[Warrant]:
    coordinator = (
        Warrant.mint_builder()
        .capability("read_text_file", {"path": Subpath(str(work / "docs"))})
        .capability("write_file", {"path": Subpath(str(work / "docs")), "content": Wildcard()})
        .holder(coordinator_key.public_key)
        .ttl(3600)
        .mint(org_key)
    )
    agent = (
        coordinator.grant_builder()
        .capability("read_text_file", {"path": Subpath(str(work / "docs"))})
        .capability("write_file", {"path": Exact(str(work / "docs/notes.md")), "content": Wildcard()})
        .holder(agent_key.public_key)
        .ttl(600)
        .grant(coordinator_key)
    )
    return [coordinator, agent]


def tenuo_meta(chain: list[Warrant], key: SigningKey, tool: str, args: dict) -> dict:
    proof = chain[-1].sign(key, tool, args, int(time.time()))
    warrant = chain[0].to_base64() if len(chain) == 1 else encode_warrant_stack(chain)
    return {"tenuo": {"warrant": warrant, "signature": base64.b64encode(bytes(proof)).decode()}}


def agent_calls(work: Path) -> list[tuple[str, str, dict]]:
    return [
        ("read the guide", "read_text_file", {"path": str(work / "docs/guide.md")}),
        ("write docs/notes.md", "write_file", {"path": str(work / "docs/notes.md"), "content": "Updated.\n"}),
        ("overwrite CI workflow", "write_file", {"path": str(work / ".github/workflows/ci.yml"), "content": "on: push\njobs: {exfil: {}}\n"}),
        ("read ../.env", "read_text_file", {"path": str(work / "docs/../.env")}),
        ("move the guide", "move_file", {"source": str(work / "docs/guide.md"), "destination": str(work / "guide.md")}),
    ]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def proxy(work: Path, with_tenuo: bool):
    """Start mcp-proxy (stock CLI, or the Tenuo launcher) in front of the filesystem server."""
    port = free_port()
    launcher = [sys.executable, str(HERE / "tenuo_mcp_proxy.py")] if with_tenuo else [sys.executable, "-m", "mcp_proxy"]
    env = {**os.environ, "TENUO_TRUSTED_ROOT": bytes(org_key.public_key.to_bytes()).hex()}
    proc = subprocess.Popen(
        [*launcher, "--port", str(port), "--", *FILESYSTEM_SERVER, str(work)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            try:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        yield session
                        return
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError("mcp-proxy exited during startup")
                await asyncio.sleep(0.5)
        raise RuntimeError("mcp-proxy did not come up")
    finally:
        proc.terminate()
        proc.wait()


async def run(with_tenuo: bool, work: Path | None = None, calls=None):
    work = work or make_project()
    chain = warrants(work)
    results = []
    async with proxy(work, with_tenuo) as session:
        for label, tool, args in calls or agent_calls(work):
            meta = tenuo_meta(chain, agent_key, tool, args)
            res = await session.call_tool(tool, args, meta=meta)
            text = "".join(getattr(b, "text", "") for b in res.content)
            results.append((label, not res.isError, text))
    return work, results


def report(title: str, work: Path, results) -> None:
    print(f"\n{title}")
    for label, ok, text in results:
        verdict = "ran" if ok else f"REFUSED  {text.splitlines()[0][:80]}"
        print(f"  {label:24} {verdict}")
    ci = (work / ".github/workflows/ci.yml").read_text()
    print(f"  -> ci.yml {'OVERWRITTEN' if 'exfil' in ci else 'untouched'}, guide.md {'moved' if not (work / 'docs/guide.md').exists() else 'in place'}")


def main() -> None:
    work, results = asyncio.run(run(with_tenuo=False))
    report("stock mcp-proxy (anyone who can reach it, or holds its bearer token):", work, results)
    work, results = asyncio.run(run(with_tenuo=True))
    report("mcp-proxy + Tenuo (the agent's warrant: read docs/, write docs/notes.md):", work, results)


if __name__ == "__main__":
    main()
