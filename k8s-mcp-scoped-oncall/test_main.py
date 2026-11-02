"""Runs the real Kubernetes MCP server (built by ./setup.sh) with a recording fake kubectl."""

import asyncio

import pytest
from tenuo import Exact, Range, SigningKey, Warrant, Wildcard
from tenuo.exceptions import MonotonicityError

import main

TASK_ONLY = [
    "rollout restart deployment/checkout -n staging",
    "scale deployment checkout --replicas=3 --namespace=staging",
]


def test_non_destructive_mode_alone_lets_every_call_through():
    results, log = asyncio.run(main.run(with_tenuo=False))
    assert all(ran for _, ran, _, _ in results)
    assert len(log) == len(main.AGENT_CALLS)


def test_tenuo_lets_only_the_task_reach_kubectl():
    results, log = asyncio.run(main.run(with_tenuo=True))
    assert log == TASK_ONLY
    refused = {label: text for label, ran, _, text in results if not ran}
    assert "namespace" in refused["scale checkout/production 0"]
    assert "replicas" in refused["scale checkout/staging 50"]
    assert "name" in refused["restart payments/staging"]
    assert "context" in refused["scale on another cluster"]
    assert "missing required argument" in refused["scale, namespace omitted"]
    assert "kubectl_apply" in refused["apply cluster-admin binding"]


def test_calls_without_valid_authority_never_reach_kubectl():
    call = [main.AGENT_CALLS[1]]  # an otherwise allowed scale
    rogue, key = SigningKey.generate(), SigningKey.generate()
    untrusted = (
        Warrant.mint_builder()
        .capability("kubectl_scale", {k: Wildcard() for k in call[0][2]})
        .holder(key.public_key)
        .ttl(60)
        .mint(rogue)
    )
    chain = [main.commander_warrant, main.oncall_warrant_for("checkout", "staging", 5)]
    cases = {
        "no warrant": (dict(attach=False), "missing _meta.tenuo"),
        "untrusted root": (dict(chain=[untrusted], key=key), "TENUO_UNTRUSTED_ROOT"),
        "wrong holder key": (dict(chain=chain, key=SigningKey.generate()), "Proof-of-Possession"),
        "child without parent": (dict(chain=chain[-1:]), "TENUO_UNTRUSTED_ROOT"),
    }
    for label, (kwargs, reason) in cases.items():
        results, log = asyncio.run(main.run(with_tenuo=True, calls=call, **kwargs))
        assert log == [], label
        assert results[0][2] and reason in results[0][3], label


def test_commander_cannot_delegate_beyond_its_own_scope():
    with pytest.raises(Exception):
        main.oncall_warrant_for("billing", "staging", 5)
    with pytest.raises(MonotonicityError):
        main.oncall_warrant_for("checkout", "staging", 20)


def test_oncall_agent_cannot_redelegate_wider():
    oncall = main.oncall_warrant_for("checkout", "staging", 5)
    with pytest.raises(Exception):
        (
            oncall.grant_builder()
            .capability(
                "kubectl_scale",
                {"resourceType": Exact("deployment"), "name": Exact("checkout"), "namespace": Exact("production"), "replicas": Range(max=5)},
            )
            .holder(SigningKey.generate().public_key)
            .grant(main.oncall_key)
        )
