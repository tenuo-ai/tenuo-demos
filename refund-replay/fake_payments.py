"""Offline stand-in for a payments API, so the demo runs without an account.

Records every refund it issues. The demo reads this list back to show what
actually happened, not just what the server answered.
"""

refunds: list[dict] = []


def refund(invoice_id: str, amount_cents: int, currency: str) -> str:
    refund_id = f"re_{len(refunds) + 1:03d}"
    refunds.append({"id": refund_id, "invoice_id": invoice_id, "amount_cents": amount_cents, "currency": currency})
    return refund_id


def total_cents() -> int:
    return sum(r["amount_cents"] for r in refunds)
