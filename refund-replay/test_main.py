import asyncio
import base64
import time

import pytest
from tenuo import NonceStore

import fake_payments
import main
from server import build_server


@pytest.fixture(autouse=True)
def reset():
    fake_payments.refunds.clear()


def run(scene):
    steps = asyncio.run(scene())
    return [ok for _, _, ok, _ in steps], [text for _, _, _, text in steps]


def test_without_a_store_the_replay_is_refunded_twice():
    oks, _ = run(main.no_replay_protection)
    assert oks == [True, True]
    assert fake_payments.total_cents() == 8000


def test_nonce_store_refuses_the_replay():
    oks, texts = run(main.with_nonce_store)
    assert oks == [True, False] and "replay" in texts[1].lower()
    assert fake_payments.total_cents() == 4000


def test_stale_request_is_refused_without_a_store():
    oks, _ = run(main.stale_request)
    assert oks == [False]
    assert fake_payments.refunds == []


def test_a_store_per_replica_misses_a_replay_sent_to_the_other_replica():
    oks, _ = run(main.store_per_replica)
    assert oks == [True, True]
    assert fake_payments.total_cents() == 8000


def test_a_shared_store_refuses_the_replay_on_any_replica():
    oks, texts = run(main.shared_store)
    assert oks == [True, False] and "replay" in texts[1].lower()
    assert fake_payments.total_cents() == 4000


def test_an_unreachable_store_fails_closed():
    oks, _ = run(main.store_down)
    assert oks == [False]
    assert fake_payments.refunds == []


def test_a_new_call_within_the_warrant_is_allowed():
    oks, _ = run(main.within_scope)
    assert oks == [True, True]
    assert fake_payments.total_cents() == 7900


def test_an_identical_retry_in_the_same_window_is_refused():
    # The PoP preimage rounds the timestamp to its window, so a retry with identical
    # arguments signed moments later produces the same signature.
    server = build_server(main.org_key.public_key, nonce_store=NonceStore())
    ts = int(time.time())
    first = asyncio.run(main.send(server, main.signed_request(main.REFUND, timestamp=ts)))
    retry = asyncio.run(main.send(server, main.signed_request(main.REFUND, timestamp=ts)))
    assert first[0] and not retry[0]
    assert fake_payments.total_cents() == 4000


def test_the_warrant_still_applies_with_a_store():
    server = build_server(main.org_key.public_key, nonce_store=NonceStore())
    ok, text = asyncio.run(main.send(server, main.signed_request({**main.REFUND, "amount_cents": 5000})))
    assert not ok and "'amount_cents'" in text
    assert fake_payments.refunds == []


def test_a_refused_call_does_not_use_up_its_proof():
    # The nonce is recorded only after the warrant check passes.
    store = NonceStore()
    server = build_server(main.org_key.public_key, nonce_store=store)

    def proof(request):
        return base64.b64decode(request[1]["tenuo"]["signature"])

    over_limit = main.signed_request({**main.REFUND, "amount_cents": 5000})
    asyncio.run(main.send(server, over_limit))
    assert not store.is_replay(proof(over_limit))

    allowed = main.signed_request(main.REFUND)
    asyncio.run(main.send(server, allowed))
    assert store.is_replay(proof(allowed))  # control: an accepted proof is recorded
