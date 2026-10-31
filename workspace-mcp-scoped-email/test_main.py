import asyncio

import pytest
from tenuo import Exact, SigningKey, Warrant, Wildcard
from tenuo.exceptions import MonotonicityError

import fake_google
import main
from server import build_server

fake_google.install()
SERVER = build_server(main.org_key.public_key)
CHAIN = [main.coordinator_warrant, main.drafter_warrant_for("bob@acme.com", "thread-4471")]


@pytest.fixture(autouse=True)
def reset():
    fake_google.sent.clear()


def send(args, chain=CHAIN, key=main.drafter_key, meta=True):
    async def go():
        async with main.Client(SERVER) as client:
            if not meta:
                r = await client.call_tool("send_gmail_message", args, raise_on_error=False)
                return not r.is_error, "".join(getattr(b, "text", "") for b in r.content)
            return await main.call(client, chain, key, "send_gmail_message", args)

    return asyncio.run(go())


def test_scoped_reply_is_sent_once_and_nothing_else_goes_out():
    results = asyncio.run(main.run(SERVER))
    assert [ok for _, ok, _ in results] == [True, False, False, False]
    assert fake_google.sent == [{"To": "bob@acme.com", "Subject": "Re: INV-4471"}]
    assert "'to'" in results[1][2] and "'bcc'" in results[2][2] and "'forward_message_id'" in results[3][2]


def test_other_thread_is_denied():
    ok, text = send(main.reply(thread_id="thread-9999"))
    assert not ok and "'thread_id'" in text and fake_google.sent == []


def test_call_without_a_warrant_is_refused():
    ok, text = send(main.reply(), meta=False)
    assert not ok and "No warrant" in text and fake_google.sent == []


def test_stolen_warrant_without_the_holder_key_is_refused():
    ok, text = send(main.reply(), key=SigningKey.generate())
    assert not ok and "Proof-of-Possession" in text and fake_google.sent == []


def test_delegated_warrant_without_its_parent_is_refused():
    ok, text = send(main.reply(), chain=CHAIN[-1:])
    assert not ok and "not trusted" in text and fake_google.sent == []


def test_warrant_from_an_untrusted_root_is_refused():
    rogue, key = SigningKey.generate(), SigningKey.generate()
    w = (
        Warrant.mint_builder()
        .capability("send_gmail_message", {k: Wildcard() for k in main.reply()})
        .holder(key.public_key)
        .ttl(60)
        .mint(rogue)
    )
    ok, text = send(main.reply(), chain=[w], key=key)
    assert not ok and "not trusted" in text and fake_google.sent == []


def test_camel_case_alias_cannot_smuggle_an_argument():
    ok, text = send(main.reply(fromEmail="ceo@acme.com"))
    assert not ok and "'fromEmail'" in text and fake_google.sent == []


@pytest.mark.parametrize(
    "to",
    ["eve@evil.com,bob@acme.com", "eve@evil.com, bob@acme.com", "Eve <eve@evil.com>, x@acme.com", "eve@evil.com;x@acme.com"],
)
def test_recipient_list_cannot_sneak_an_outside_address_past_the_domain_rule(to):
    ok, text = send(main.reply(to=to), chain=[main.coordinator_warrant], key=main.coordinator_key)
    assert not ok and "'to'" in text and fake_google.sent == []
    with pytest.raises(Exception):
        main.drafter_warrant_for(to, "thread-4471")


def test_coordinator_cannot_delegate_outside_acme():
    with pytest.raises(MonotonicityError):
        main.drafter_warrant_for("someone@outside.example", "thread-4471")


def test_drafter_cannot_redelegate_a_wider_recipient():
    child = CHAIN[-1]
    with pytest.raises(MonotonicityError):
        (
            child.grant_builder()
            .capability(
                "send_gmail_message",
                {
                    "user_google_email": Exact(main.ME),
                    "to": Wildcard(),
                    "thread_id": Exact("thread-4471"),
                    "subject": Wildcard(),
                    "body": Wildcard(),
                },
            )
            .holder(SigningKey.generate().public_key)
            .grant(main.drafter_key)
        )
