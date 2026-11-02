"""Runs the real mcp-proxy CLI in front of the real filesystem server (needs npx)."""

import asyncio

import pytest
from tenuo import Exact, SigningKey, Subpath, Warrant, Wildcard
from tenuo.exceptions import MonotonicityError

import main


def results_by_label(results):
    return {label: (ok, text) for label, ok, text in results}


def test_stock_proxy_lets_every_call_through():
    work, results = asyncio.run(main.run(with_tenuo=False))
    assert all(ok for _, ok, _ in results)
    assert "exfil" in (work / ".github/workflows/ci.yml").read_text()


def test_tenuo_proxy_forwards_only_the_task():
    work = main.make_project()
    calls = main.agent_calls(work) + [
        ("write another docs file", "write_file", {"path": str(work / "docs/other.md"), "content": "x"}),
    ]
    work, results = asyncio.run(main.run(with_tenuo=True, work=work, calls=calls))
    r = results_by_label(results)

    assert r["read the guide"][0] and r["write docs/notes.md"][0]
    assert (work / "docs/notes.md").read_text() == "Updated.\n"

    for label in ("overwrite CI workflow", "read ../.env", "move the guide", "write another docs file"):
        assert not r[label][0] and "Tenuo denied" in r[label][1]
    assert (work / ".github/workflows/ci.yml").read_text() == "on: push\n"
    assert (work / "docs/guide.md").exists()
    assert not (work / "docs/other.md").exists()  # the coordinator could; the agent's warrant can't
    assert "s3cret" not in r["read ../.env"][1]


def test_calls_without_valid_authority_never_reach_the_server():
    work = main.make_project()
    call = [("write CI", "write_file", {"path": str(work / ".github/workflows/ci.yml"), "content": "pwned"})]
    rogue, key = SigningKey.generate(), SigningKey.generate()
    untrusted = (
        Warrant.mint_builder()
        .capability("write_file", {"path": Wildcard(), "content": Wildcard()})
        .holder(key.public_key)
        .ttl(60)
        .mint(rogue)
    )

    async def go():
        out = {}
        async with main.proxy(work, with_tenuo=True) as session:
            label, tool, args = call[0]
            res = await session.call_tool(tool, args)
            out["no warrant"] = res
            res = await session.call_tool(tool, args, meta=main.tenuo_meta([untrusted], key, tool, args))
            out["untrusted root"] = res
            chain = main.warrants(work)
            res = await session.call_tool(tool, args, meta=main.tenuo_meta(chain, SigningKey.generate(), tool, args))
            out["wrong holder key"] = res
        return out

    out = asyncio.run(go())
    text = {k: res.content[0].text for k, res in out.items()}
    assert all(res.isError for res in out.values())
    assert "No warrant" in text["no warrant"]
    assert "not trusted" in text["untrusted root"]
    assert "Proof-of-Possession" in text["wrong holder key"]
    assert (work / ".github/workflows/ci.yml").read_text() == "on: push\n"


def test_agent_cannot_redelegate_wider_than_it_holds():
    work = main.make_project()
    agent = main.warrants(work)[-1]
    with pytest.raises(MonotonicityError):
        (
            agent.grant_builder()
            .capability("write_file", {"path": Subpath(str(work)), "content": Wildcard()})
            .holder(SigningKey.generate().public_key)
            .grant(main.agent_key)
        )
    with pytest.raises(Exception):
        (
            agent.grant_builder()
            .capability("write_file", {"path": Exact(str(work / ".github/workflows/ci.yml")), "content": Wildcard()})
            .holder(SigningKey.generate().public_key)
            .grant(main.agent_key)
        )
