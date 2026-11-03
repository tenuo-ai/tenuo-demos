"""live.py's flow, run offline against fake_google. No Google account needed."""

import asyncio

import pytest
from tenuo.exceptions import MonotonicityError

import fake_google
import live
from main import call
from server import build_server

ME = "me@acme.com"
fake_google.install()


@pytest.fixture(autouse=True)
def reset():
    fake_google.sent.clear()


def test_live_flow_sends_the_ticket_and_the_reply_and_nothing_else():
    assert asyncio.run(live.run(ME)) == 0
    assert [m["To"] for m in fake_google.sent] == ["me+bob@acme.com", "me+bob@acme.com"]
    assert fake_google.sent[1]["Subject"].startswith("Re: INV-4471")


@pytest.mark.parametrize("to", [ME, "me+bob@acme.com", "me+anything-1@acme.com"])
def test_own_address_rule_allows_you_and_your_plus_tags(to):
    assert live.own_address_rule(ME).matches(to)


@pytest.mark.parametrize(
    "to",
    [
        "eve@evil.com",
        "me@acme.com.evil.com",
        "xme@acme.com",
        "me@acmeXcom",
        "eve@evil.com,me@acme.com",
        "me@acme.com, eve@evil.com",
        "Eve <eve@evil.com>, me@acme.com",
        "me@acme.com;eve@evil.com",
    ],
)
def test_own_address_rule_refuses_everyone_else(to):
    assert not live.own_address_rule(ME).matches(to)


def test_address_with_a_plus_tag_is_rejected_up_front():
    with pytest.raises(ValueError):
        live.own_address_rule("me+x@acme.com")


def test_coordinator_cannot_delegate_to_someone_else():
    with pytest.raises(MonotonicityError):
        live.drafter_warrant(live.coordinator_warrant(ME), ME, live.OUTSIDE, "thread-1")


def test_setup_warrant_sends_only_the_exact_ticket():
    ticket = {"user_google_email": ME, "to": "me+bob@acme.com", "subject": "s", "body": "b"}
    chain = [live.setup_warrant(ME, ticket, "subject:x")]

    async def go():
        async with live.Client(build_server(live.org_key.public_key)) as client:
            return await call(client, chain, live.setup_key, "send_gmail_message", {**ticket, "to": live.OUTSIDE})

    ok, text = asyncio.run(go())
    assert not ok and "'to'" in text and fake_google.sent == []
