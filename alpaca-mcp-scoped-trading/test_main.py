"""Runs the released alpaca-mcp-server, with and without python -m tenuo.mcp.wrap, against a fake Alpaca API."""

import asyncio

import pytest
from tenuo import CEL, Exact, SigningKey, Warrant, Wildcard
from tenuo.exceptions import MonotonicityError

import main

TASK_ORDER = 'POST /v2/orders {"symbol":"AAPL","side":"buy","type":"limit","time_in_force":"day","qty":"10","limit_price":"228.50"}'


def test_paper_trading_and_toolsets_alone_let_every_call_through():
    results, writes = asyncio.run(main.run(with_tenuo=False))
    assert all(reached for _, reached, _, _ in results)
    assert any(line.startswith("DELETE /v2/positions") for line in writes)
    assert any('"symbol":"NVDA"' in line for line in writes)


def test_tenuo_lets_only_the_task_reach_alpaca():
    results, writes = asyncio.run(main.run(with_tenuo=True))
    assert writes == [TASK_ORDER]
    refused = {label: text for label, reached, _, text in results if not reached}
    assert "'symbol'" in refused["buy 10 NVDA"]
    assert "'qty'" in refused["buy 50 AAPL"]
    assert "'limit_price'" in refused["buy 10 AAPL, limit $900"]
    assert "missing required argument" in refused["buy 10 AAPL at market"]
    assert "'side'" in refused["sell 10 AAPL"]
    assert "close_all_positions" in refused["close all positions"]
    assert "cancel_all_orders" in refused["cancel all orders"]


@pytest.mark.parametrize("qty", ["10.5", "1e9", "NaN", "inf", "-1", "0", "0x10", "abc"])
def test_quantity_cap_holds_for_odd_numbers(qty):
    call = [("odd qty", "place_stock_order", main.order(qty=qty))]
    results, writes = asyncio.run(main.run(with_tenuo=True, calls=call))
    assert writes == [], qty


def test_calls_without_valid_authority_never_reach_alpaca():
    call = [main.AGENT_CALLS[0]]  # the allowed order
    rogue, key = SigningKey.generate(), SigningKey.generate()
    untrusted = (
        Warrant.mint_builder()
        .capability("place_stock_order", {k: Wildcard() for k in call[0][2]})
        .holder(key.public_key)
        .ttl(60)
        .mint(rogue)
    )
    chain = [main.manager_warrant, main.agent_warrant_for("AAPL", 10, 230)]
    cases = {
        "no warrant": (dict(attach=False), "No warrant provided"),
        "untrusted root": (dict(chain=[untrusted], key=key), "not trusted"),
        "wrong holder key": (dict(chain=chain, key=SigningKey.generate()), "Proof-of-Possession"),
        "child without parent": (dict(chain=chain[-1:]), "not trusted"),
    }
    for label, (kwargs, reason) in cases.items():
        results, writes = asyncio.run(main.run(with_tenuo=True, calls=call, **kwargs))
        assert writes == [], label
        assert results[0][2] and reason in results[0][3], (label, results[0][3])


def test_manager_cannot_delegate_beyond_its_own_scope():
    with pytest.raises(Exception):
        main.agent_warrant_for("TSLA", 10, 230)
    with pytest.raises(MonotonicityError):
        (
            main.manager_warrant.grant_builder()
            .capability("place_stock_order", {"symbol": Exact("AAPL"), "side": Exact("buy"), "qty": CEL("double(value) <= 1000.0"),
                                              "type": Exact("limit"), "limit_price": CEL("double(value) > 0.0"), "time_in_force": Exact("day")})
            .holder(SigningKey.generate().public_key)
            .grant(main.manager_key)
        )


def test_agent_cannot_redelegate_wider():
    agent = main.agent_warrant_for("AAPL", 10, 230)
    with pytest.raises(Exception):
        (
            agent.grant_builder()
            .capability("place_stock_order", {"symbol": Exact("AAPL"), "side": Exact("sell"), "qty": CEL("double(value) <= 10.0"),
                                              "type": Exact("limit"), "limit_price": CEL("double(value) <= 230.0"), "time_in_force": Exact("day")})
            .holder(SigningKey.generate().public_key)
            .grant(main.agent_key)
        )
