"""The refund that happens twice: replaying a signed tool call, and stopping it.

A support agent holds a warrant to refund up to $40 on one invoice. It signs one
refund call. Anyone who can read that request (a log of MCP traffic, a proxy, a
retry queue) can send the same bytes again. The warrant is valid, the signature
is valid and the arguments match, so a stateless check can't tell it's a repeat.

A NonceStore remembers each proof of possession the server has accepted and
refuses the second presentation. Runs offline: fake_payments stands in for the
payments API.
"""

import asyncio
import base64
import logging
import time

from fastmcp import Client
from tenuo import Exact, NonceStore, Range, SigningKey, Warrant

import fake_payments
from server import build_server

org_key = SigningKey.generate()  # the operator's trust root; the server trusts only this
agent_key = SigningKey.generate()

warrant = (
    Warrant.mint_builder()
    .capability(
        "issue_refund",
        {
            "invoice_id": Exact("INV-4471"),
            "amount_cents": Range(max=4000),
            "currency": Exact("usd"),
        },
    )
    .holder(agent_key.public_key)
    .ttl(600)
    .mint(org_key)
)

REFUND = {"invoice_id": "INV-4471", "amount_cents": 4000, "currency": "usd"}


def signed_request(args: dict, timestamp: int | None = None) -> tuple[dict, dict]:
    """A tools/call as a Tenuo client sends it: the arguments, the warrant and a proof of possession."""
    ts = int(time.time()) if timestamp is None else timestamp
    proof = warrant.sign(agent_key, "issue_refund", args, ts)
    meta = {"tenuo": {"warrant": warrant.to_base64(), "signature": base64.b64encode(bytes(proof)).decode()}}
    return args, meta


async def send(server, request: tuple[dict, dict]) -> tuple[bool, str]:
    args, meta = request
    async with Client(server) as client:
        result = await client.call_tool("issue_refund", args, meta=meta, raise_on_error=False)
    return (not result.is_error), "".join(getattr(block, "text", "") for block in result.content)


class UnreachableStore:
    """A shared nonce backend that is down."""

    def seen(self, nonce_hex: str) -> bool:
        raise ConnectionError("nonce store unreachable")

    def record(self, nonce_hex: str, ttl_seconds: int) -> None:
        raise ConnectionError("nonce store unreachable")


async def no_replay_protection():
    server = build_server(org_key.public_key)
    request = signed_request(REFUND)
    return [
        ("agent", "refunds $40 on INV-4471", *await send(server, request)),
        ("attacker", "sends the same request again", *await send(server, request)),
    ]


async def with_nonce_store():
    server = build_server(org_key.public_key, nonce_store=NonceStore())
    request = signed_request(REFUND)
    return [
        ("agent", "refunds $40 on INV-4471", *await send(server, request)),
        ("attacker", "sends the same request again", *await send(server, request)),
    ]


async def stale_request():
    # No store here: the timestamp window alone refuses a request captured long ago.
    server = build_server(org_key.public_key)
    captured = signed_request(REFUND, timestamp=int(time.time()) - 300)
    return [("attacker", "replays a request captured 5 min ago", *await send(server, captured))]


async def store_per_replica():
    replica_a = build_server(org_key.public_key, nonce_store=NonceStore(), name="payments-a")
    replica_b = build_server(org_key.public_key, nonce_store=NonceStore(), name="payments-b")
    request = signed_request(REFUND)
    return [
        ("agent", "refunds $40 via replica A", *await send(replica_a, request)),
        ("attacker", "replays it to replica B", *await send(replica_b, request)),
    ]


async def shared_store():
    store = NonceStore()  # in production, a NonceStore backed by Redis or similar
    replica_a = build_server(org_key.public_key, nonce_store=store, name="payments-a")
    replica_b = build_server(org_key.public_key, nonce_store=store, name="payments-b")
    request = signed_request(REFUND)
    return [
        ("agent", "refunds $40 via replica A", *await send(replica_a, request)),
        ("attacker", "replays it to replica B", *await send(replica_b, request)),
    ]


async def store_down():
    server = build_server(org_key.public_key, nonce_store=NonceStore(backend=UnreachableStore()))
    return [("agent", "refunds $40 while the store is down", *await send(server, signed_request(REFUND)))]


async def within_scope():
    # Not a replay: the agent signs a new call with different arguments. The warrant
    # allows it, so it goes through. Warrants limit each call; they don't count calls.
    server = build_server(org_key.public_key, nonce_store=NonceStore())
    return [
        ("agent", "refunds $40 on INV-4471", *await send(server, signed_request(REFUND))),
        ("agent", "signs a new refund for $39", *await send(server, signed_request({**REFUND, "amount_cents": 3900}))),
    ]


SCENES = [
    ("1. no replay protection", no_replay_protection),
    ("2. with a NonceStore", with_nonce_store),
    ("3. a request captured long ago (no store)", stale_request),
    ("4. two replicas, a store each", store_per_replica),
    ("5. two replicas, one shared store", shared_store),
    ("6. the shared store is down", store_down),
    ("7. what a NonceStore doesn't stop", within_scope),
]


def short(reason: str, width: int = 80) -> str:
    """The denial's first sentence, cut at a word boundary to fit one line."""
    first = reason.splitlines()[0].split(". ")[0]
    return first if len(first) <= width else first[:width].rsplit(" ", 1)[0] + " …"


def main() -> None:
    logging.disable(logging.ERROR)
    for title, scene in SCENES:
        fake_payments.refunds.clear()
        print(f"\n== {title}")
        for actor, label, ok, text in asyncio.run(scene()):
            verdict = f"ALLOWED  {text}" if ok else f"DENIED   {short(text)}"
            print(f"  {actor:9} {label:38} {verdict}")
        count, total = len(fake_payments.refunds), fake_payments.total_cents()
        print(f"  refunded: ${total / 100:.2f} in {count} refund{'s' if count != 1 else ''}")


if __name__ == "__main__":
    main()
