# The refund that happens twice

A support agent may refund up to $40 on invoice INV-4471. It signs one refund
call and sends it to the payments MCP server. Somebody who can read that
request (a log of MCP traffic, a debugging proxy, a retry queue) sends the same
bytes again. Does the customer get $80?

Without replay protection, yes. The warrant is valid, the signature is valid and
the arguments match the warrant, so a check that keeps no state can't tell the
second request from the first. With a `NonceStore`, the server remembers each
proof of possession it has accepted and refuses the copy.

```text
agent      issue_refund(INV-4471, 4000 cents) + warrant + proof of possession
   |
   |  request is logged / proxied / queued
   v
attacker   sends the identical request again
   |
   v
payments MCP server   warrant ok, signature ok, arguments ok ... seen this proof before?
```

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

No payments account needed: `fake_payments.py` stands in for the payments API
and records every refund. The `refunded:` lines are read back from it.

## Why a valid warrant isn't enough

Every Tenuo tool call carries a proof of possession: the agent signs the warrant
ID, the tool, the exact arguments and a timestamp with its private key. That
stops a stolen warrant being used without the key, and stops anyone changing
the arguments. It doesn't stop someone resending a request the agent already
signed.

Tenuo's verification is stateless by design, so it bounds that with time. The
signed timestamp is rounded to a 30-second window, and the verifier accepts the
current window and two either side: roughly 60 to 90 seconds. Scene 3 shows a
request captured five minutes ago being refused with no store at all. Inside
that window, scene 1 shows the copy going through.

For calls with side effects (refunds, payments, emails, deletes) you close the
gap by giving the verifier a `NonceStore`:

```python
from tenuo import Authorizer, NonceStore
from tenuo.mcp import MCPVerifier, TenuoMiddleware

verifier = MCPVerifier(
    authorizer=Authorizer(trusted_roots=[org_public_key]),
    nonce_store=NonceStore(),   # remembers each accepted proof for 120 s
)
server.add_middleware(TenuoMiddleware(verifier))
```

That is the whole change; see `server.py`. The store records a proof only after
the warrant, signature and arguments have all passed, so a refused call doesn't
use one up.

## More than one server

`NonceStore()` keeps its memory in the process. Run two replicas behind a load
balancer and each has its own: a request accepted by replica A can be replayed
to replica B (scene 4). Give every replica the same backing store and the copy
is refused wherever it lands (scene 5).

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

If the store can't be reached, the call is refused, including the agent's own
legitimate one (scene 6). No check, no refund.

## What it doesn't stop

A `NonceStore` refuses a proof it has seen before. It doesn't count calls. In
scene 7 the agent signs a second, new refund for $39; that's a different call,
the warrant allows it, and it goes through. The customer gets $79. What limits
the damage there is the warrant itself: one invoice, at most $40 per call, ten
minutes. Keep warrants for side-effecting tools that narrow and that short.

One more thing to know: because the timestamp is rounded to its window, a
retry with identical arguments signed moments after the first produces the
same signature, so the store refuses it too. For refunds that's the behaviour
you want. If a client legitimately needs to repeat an identical call, it has
to wait for the next window.

## Tests

```bash
uv run pytest
```

- without a store the copy is refunded; with one it's refused, and only $40 goes out
- a request captured five minutes ago is refused even without a store
- a store per replica misses a copy sent to the other replica; a shared store doesn't
- an unreachable store refuses the call and nothing is refunded
- a new call within the warrant is allowed; an identical retry in the same window isn't
- the warrant still applies with a store, and a refused call doesn't use up its proof

Tested with tenuo 0.3.5 and fastmcp 4.1.4.
