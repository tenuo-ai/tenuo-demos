"""Payment execution tools for the AP automation agent."""

import json
import uuid

from langchain_core.tools import tool

from tools.db import get_pool


@tool
async def initiate_payment(
    invoice_id: str,
    vendor_id: str,
    amount: float,
    bank_account: str | None = None,
    bank_routing: str | None = None,
) -> str:
    """Initiate a payment for an approved invoice.

    Requires the vendor's bank account and routing number. Look up the vendor's
    bank details first and pass them here. The payment will be sent to the
    specified bank account.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # If bank details not provided, look them up from vendor record
        if not bank_account or not bank_routing:
            vendor = await conn.fetchrow(
                "SELECT bank_account, bank_routing FROM vendors WHERE id = $1",
                vendor_id,
            )
            if not vendor:
                return f"Vendor {vendor_id} not found."
            bank_account = bank_account or vendor["bank_account"]
            bank_routing = bank_routing or vendor["bank_routing"]

        # Get invoice to verify it's approved
        invoice = await conn.fetchrow(
            "SELECT status, currency FROM invoices WHERE id = $1",
            invoice_id,
        )
        if not invoice:
            return f"Invoice {invoice_id} not found."
        if invoice["status"] != "approved":
            return f"Invoice {invoice_id} is not approved (status: {invoice['status']})."

        payment_id = f"PAY-2024-{uuid.uuid4().hex[:4].upper()}"
        await conn.execute(
            """INSERT INTO payments (id, invoice_id, vendor_id, amount, currency,
                                    bank_account, bank_routing, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')""",
            payment_id,
            invoice_id,
            vendor_id,
            amount,
            invoice["currency"],
            bank_account,
            bank_routing,
        )

        # Mark invoice as paid
        await conn.execute(
            "UPDATE invoices SET status = 'paid' WHERE id = $1",
            invoice_id,
        )

    return json.dumps(
        {
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "vendor_id": vendor_id,
            "amount": amount,
            "bank_account": bank_account,
            "bank_routing": bank_routing,
            "status": "pending",
        },
        indent=2,
    )


@tool
async def approve_payment(payment_id: str, approved_by: str = "agent") -> str:
    """Approve a pending payment for execution."""
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE payments SET status = 'approved', approved_by = $2
           WHERE id = $1 AND status = 'pending'""",
        payment_id,
        approved_by,
    )
    if result == "UPDATE 0":
        return f"Payment {payment_id} not found or not in pending status."
    return f"Payment {payment_id} approved by {approved_by}."


@tool
async def get_fx_rate(from_currency: str, to_currency: str) -> str:
    """Get the current foreign exchange rate between two currencies.

    Returns a realistic mock rate for demo purposes.
    """
    rates = {
        ("USD", "EUR"): 0.92,
        ("EUR", "USD"): 1.087,
        ("USD", "GBP"): 0.79,
        ("GBP", "USD"): 1.266,
        ("EUR", "GBP"): 0.858,
        ("GBP", "EUR"): 1.165,
        ("USD", "SEK"): 10.45,
        ("SEK", "USD"): 0.0957,
        ("USD", "HKD"): 7.82,
        ("HKD", "USD"): 0.1279,
    }
    pair = (from_currency.upper(), to_currency.upper())
    if pair[0] == pair[1]:
        return json.dumps({"from": pair[0], "to": pair[1], "rate": 1.0})
    rate = rates.get(pair)
    if rate is None:
        return f"FX rate not available for {from_currency} -> {to_currency}."
    return json.dumps({"from": pair[0], "to": pair[1], "rate": rate})
