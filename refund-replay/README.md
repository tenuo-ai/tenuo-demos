# The refund that happens twice

A support agent is allowed to refund up to $40 on one invoice. It sends one
correct, properly signed refund request. Someone copies that request and sends
it again. Does the customer get $80?

## What this demo shows

Most agent attacks trick the agent into asking for the wrong thing: the wrong
account, the wrong file, the wrong recipient. A Tenuo warrant stops those,
because the request doesn't match what the warrant allows.

This demo is about a different gap. Nobody tricks the agent. Its request is
exactly right: right invoice, right amount, signed by the right key. The
problem is that the same request can be **delivered twice**. Every check
passes both times, so a warrant alone can't tell the copy from the original.

The demo shows that gap happening, then closes it with Tenuo's `NonceStore`:
a small record of requests the server has already accepted. It also shows what
that record needs to work in production (a store shared by every server) and
what it still doesn't stop.

## How it works

```text
support agent   signs:  issue_refund(INV-4471, $40)  + warrant + proof of possession
      |
      |  the request passes through a log, a proxy or a retry queue
      v
attacker        resends the identical request
      |
      v
payments MCP server (Tenuo middleware)
      1. is the warrant genuine, from a trusted issuer, unexpired?
      2. was this request signed by the key the warrant names?
      3. do the arguments fit the warrant?
      4. (with a NonceStore) has this exact signed request been accepted before?
      |
      v
fake payments API   records every refund that actually goes out
```

The pieces:

| Piece | File | Role |
|---|---|---|
| The warrant | `main.py` | Issued by the operator's key to the support agent: `issue_refund` only, invoice `INV-4471` only, at most 4000 cents, USD, valid for 10 minutes. |
| The signed request | `main.py`, `signed_request()` | The arguments plus the warrant and a *proof of possession*: the agent's signature over the warrant ID, tool name, exact arguments and a timestamp. This is what a Tenuo client attaches to every MCP `tools/call`. |
| The attacker | `main.py` | Has a copy of a signed request but not the agent's key. It can only resend requests, not create or change them. |
| The server | `server.py` | A FastMCP payments server with one tool, `issue_refund`, and Tenuo's `TenuoMiddleware` checking every call. `build_server(..., nonce_store=...)` turns replay protection on or off. |
| The payments API | `fake_payments.py` | Stands in for a real payments provider, so the demo runs offline with no account. It records every refund, and the `refunded:` line in each scene is read back from it, not taken from the server's reply. |

## Run it

```bash
uv run main.py
```

```text
== 1. no replay protection
  agent     refunds $40 on INV-4471                ALLOWED  re_001
  attacker  sends the same request again           ALLOWED  re_002
  refunded: $80.00 in 2 refunds

== 2. with a NonceStore
  agent     refunds $40 on INV-4471                ALLOWED  re_001
  attacker  sends the same request again           DENIED   PoP replay detected — this exact authorization token was already consumed
  refunded: $40.00 in 1 refund

== 3. a request captured long ago (no store)
  attacker  replays a request captured 5 min ago   DENIED   Access denied: Signature verification failed: Proof-of-Possession verification …
  refunded: $0.00 in 0 refunds

== 4. two replicas, a store each
  agent     refunds $40 via replica A              ALLOWED  re_001
  attacker  replays it to replica B                ALLOWED  re_002
  refunded: $80.00 in 2 refunds

== 5. two replicas, one shared store
  agent     refunds $40 via replica A              ALLOWED  re_001
  attacker  replays it to replica B                DENIED   PoP replay detected — this exact authorization token was already consumed
  refunded: $40.00 in 1 refund

== 6. the shared store is down
  agent     refunds $40 while the store is down    DENIED   Internal verification error: nonce store unreachable
  refunded: $0.00 in 0 refunds

== 7. what a NonceStore doesn't stop
  agent     refunds $40 on INV-4471                ALLOWED  re_001
  agent     signs a new refund for $39             ALLOWED  re_002
  refunded: $79.00 in 2 refunds
```

Each scene starts with an empty payments ledger and builds its own server(s).

## The scenarios

| # | Scenario | Server setup | What happens | Why it's in the demo |
|---|---|---|---|---|
| 1 | **No replay protection** | Tenuo checks only (no `NonceStore`) | The agent's refund goes through. The attacker resends the identical request a moment later and it goes through too: $80 refunded. | Shows the gap. The copy passes every check because it *is* a valid request: genuine warrant, genuine signature, allowed arguments. |
| 2 | **With a NonceStore** | Same server plus `NonceStore()` | The agent's refund goes through and is recorded. The copy is refused as a replay: $40 refunded. | Shows the fix, and that it's one argument on the server. |
| 3 | **A request captured long ago** | Tenuo checks only (no `NonceStore`) | A request signed five minutes earlier is refused. Nothing refunded. | Shows what Tenuo does *without* a store: the signed timestamp limits a copy to a short window (about 60–90 seconds). Old copies are useless; only fresh ones are a risk. |
| 4 | **Two replicas, a store each** | Two servers, each with its own in-memory `NonceStore()` | The agent's refund goes to replica A. The attacker sends the copy to replica B, which has never seen it: $80 refunded. | Shows the most common deployment mistake. An in-memory store only protects the process it lives in. |
| 5 | **Two replicas, one shared store** | Two servers using the same `NonceStore` | The copy sent to replica B is refused, because the store already holds the request replica A accepted: $40 refunded. | Shows the production setup: every server checks the same store (in practice Redis or similar; see below). |
| 6 | **The shared store is down** | A `NonceStore` whose backend raises on every lookup | The agent's own, legitimate refund is refused. Nothing refunded. | Shows that replay protection fails closed. If the server can't check, it doesn't pay. |
| 7 | **What a NonceStore doesn't stop** | Server with `NonceStore()` | The agent refunds $40, then signs a **new** request for $39. Both go through: $79 refunded. | Shows the honest limit. The store refuses *copies*; it doesn't count calls. A new request that the warrant allows is not a replay. |

## Why a NonceStore

### The problem: a valid request is valid every time

Tenuo's proof of possession proves two things: the request was signed by the
key the warrant was issued to, and nobody changed a byte of it afterwards. It
does not prove the request is arriving *for the first time*. Nothing in a
signature can, because a copy is byte-for-byte identical to the original.

### Why Tenuo doesn't remember requests by default

Tenuo's verification is deliberately stateless. To check a call, a server needs
only the warrant chain, the trusted issuer keys and the clock. It never calls
out to a database or another service, so it keeps working when everything else
is down and scales without coordination.

The cost of keeping no state is that a server can't know what it has already
seen. Tenuo limits the damage with time instead: the signed timestamp is
rounded to a 30-second window, and a server accepts the current window and two
either side. A copy is only usable for roughly 60 to 90 seconds (scene 3).

For reads, that's fine: reading the same data twice does no harm. For calls
with side effects (refunds, payments, emails, deletes, deploys), one replay
inside that window is one too many.

### What a NonceStore does

A `NonceStore` gives the server a short memory for exactly those calls. When a
call passes every Tenuo check, the store saves a fingerprint of its signature
for 120 seconds, longer than any signature stays fresh. If the same signature
arrives again, the call is refused.

- It records a request only **after** the warrant, signature and arguments have
  all passed, so a refused request doesn't use anything up.
- It refuses the call if the store can't be reached (scene 6).
- It's opt-in and owned by whoever runs the server, so verification stays
  stateless everywhere it isn't needed.

Remembering one-time values to stop replays is a standard pattern: it's what
`jti` tracking does for OAuth DPoP proofs and JWTs. The IETF draft that
Tenuo implements likewise expects this tracking for calls with side effects.

### Adding one

```python
from tenuo import Authorizer, NonceStore
from tenuo.mcp import MCPVerifier, TenuoMiddleware

verifier = MCPVerifier(
    authorizer=Authorizer(trusted_roots=[org_public_key]),
    nonce_store=NonceStore(),   # remembers each accepted proof for 120 s
)
server.add_middleware(TenuoMiddleware(verifier))
```

That is the whole change; see `server.py`.

### Running more than one server

`NonceStore()` keeps its memory inside the process. Behind a load balancer,
every replica needs to check the same store, or a copy simply goes to a
replica that hasn't seen it (scenes 4 and 5).

Tenuo ships the interface, not a Redis client. A backend is two methods:

```python
class RedisNonceBackend:
    def __init__(self, redis):
        self.redis = redis

    def seen(self, nonce_hex: str) -> bool:
        return bool(self.redis.exists(f"tenuo:pop:{nonce_hex}"))

    def record(self, nonce_hex: str, ttl_seconds: int) -> None:
        self.redis.set(f"tenuo:pop:{nonce_hex}", "1", ex=ttl_seconds)

store = NonceStore(backend=RedisNonceBackend(redis_client))
```

## What it doesn't stop

A `NonceStore` refuses a request it has seen before. It doesn't count calls.
In scene 7 the agent signs a second, new refund for $39; that's a different
request, the warrant allows it, and it goes through. The customer gets $79.
What limits the damage there is the warrant itself: one invoice, at most $40
per call, ten minutes. Keep warrants for side-effecting tools that narrow and
that short.

One side effect to know about: because the timestamp is rounded to its window,
a retry with identical arguments signed moments after the first produces the
same signature, so the store refuses it too. For refunds that's the behaviour
you want. If a client legitimately needs to repeat an identical call, it has
to wait for the next window.

## Tests

```bash
uv run pytest
```

Each test checks the payments ledger, not just the server's answer, so a
refused call is proven not to have refunded anything.

- without a store the copy is refunded; with one it's refused, and only $40 goes out
- a request captured five minutes ago is refused even without a store
- a store per replica misses a copy sent to the other replica; a shared store doesn't
- an unreachable store refuses the call and nothing is refunded
- a new call within the warrant is allowed; an identical retry in the same window isn't
- the warrant still applies with a store, and a refused call doesn't use up its proof

Tested with tenuo 0.3.5 and fastmcp 4.1.4.
