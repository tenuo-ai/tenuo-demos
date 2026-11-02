"""Runs the real mcp-atlassian server against a fake Jira that records every request."""

import asyncio

import pytest
from tenuo import Exact, SigningKey, Warrant, Wildcard
from tenuo.exceptions import MonotonicityError

import main

TASK_WRITES = [
    'POST /rest/api/2/issue/OPS-12/comment {"body": "Fixed in 4.2.1, closing."}',
    'POST /rest/api/2/issue/OPS-12/transitions {"transition": {"id": "31"}}',
]


def by_label(results):
    return {label: (reached, text) for label, reached, _, text in results}


def test_native_scoping_alone_lets_every_call_through():
    results, log = asyncio.run(main.run(with_tenuo=False))
    assert all(reached for _, reached, _, _ in results)
    writes = main.jira_writes(log)
    assert 'POST /rest/api/2/issue/OPS-40/comment {"body": "Duplicate, closing."}' in writes
    assert 'POST /rest/api/2/issue/OPS-12/transitions {"transition": {"id": "41"}}' in writes
    assert any(line.startswith("GET /rest/api/2/issue/OPS-99") for line in log)


def test_tenuo_lets_only_the_task_reach_jira():
    results, log = asyncio.run(main.run(with_tenuo=True))
    assert main.jira_writes(log) == TASK_WRITES
    r = by_label(results)
    assert all(r[label][0] for label in ("read OPS-12", "comment on OPS-12", "move OPS-12 to Done"))
    for label, field in [
        ("read OPS-99 (security incident)", "issue_key"),
        ("comment on OPS-40", "issue_key"),
        ("move OPS-40 to Done", "issue_key"),
        ("move OPS-12 to Won't Do", "transition_id"),
    ]:
        reached, text = r[label]
        assert not reached and f"Constraint '{field}' not satisfied" in text, label
    assert not any("OPS-99" in line for line in log)


def test_calls_without_valid_authority_never_reach_jira():
    call = [main.AGENT_CALLS[1]]  # an otherwise allowed comment
    rogue, key = SigningKey.generate(), SigningKey.generate()
    untrusted = (
        Warrant.mint_builder()
        .capability("jira_add_comment", {"issue_key": Wildcard(), "body": Wildcard()})
        .holder(key.public_key)
        .ttl(60)
        .mint(rogue)
    )
    chain = [main.lead_warrant, main.agent_warrant_for("OPS-12", main.DONE)]
    cases = {
        "no warrant": (dict(attach=False), "No warrant provided"),
        "untrusted root": (dict(chain=[untrusted], key=key), "not trusted"),
        "wrong holder key": (dict(chain=chain, key=SigningKey.generate()), "Proof-of-Possession"),
        "child without parent": (dict(chain=chain[-1:]), "not trusted"),
    }
    for label, (kwargs, reason) in cases.items():
        results, log = asyncio.run(main.run(with_tenuo=True, calls=call, **kwargs))
        assert main.jira_writes(log) == [], label
        assert results[0][2] and reason in results[0][3], (label, results[0][3])


def test_lead_cannot_delegate_beyond_its_own_scope():
    with pytest.raises(Exception):
        main.agent_warrant_for("HR-7", main.DONE)
    with pytest.raises(Exception):
        main.agent_warrant_for("OPS-12", main.WONT_DO)


def test_agent_cannot_redelegate_wider():
    agent = main.agent_warrant_for("OPS-12", main.DONE)
    with pytest.raises(Exception):
        (
            agent.grant_builder()
            .capability("jira_add_comment", {"issue_key": Exact("OPS-40"), "body": Wildcard()})
            .holder(SigningKey.generate().public_key)
            .grant(main.agent_key)
        )


def test_arguments_the_warrant_does_not_name_are_refused():
    call = [("close with a comment", "jira_transition_issue", {"issue_key": "OPS-12", "transition_id": main.DONE, "comment": "see OPS-99"})]
    results, log = asyncio.run(main.run(with_tenuo=True, calls=call))
    assert main.jira_writes(log) == []
    assert "comment" in results[0][3]
