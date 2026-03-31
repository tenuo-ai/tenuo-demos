"""Expense review tools for the AP automation agent."""

import json

from langchain_core.tools import tool

from tools.db import get_pool


@tool
async def flag_expense(invoice_id: str, reason: str) -> str:
    """Flag an invoice for manual review. Used when anomalies are detected."""
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE invoices SET status = 'flagged', notes = COALESCE(notes, '') || $2 WHERE id = $1",
        invoice_id,
        f"\n[FLAGGED] {reason}",
    )
    if result == "UPDATE 0":
        return f"Invoice {invoice_id} not found."
    return f"Invoice {invoice_id} flagged for review: {reason}"


@tool
async def approve_expense(invoice_id: str, amount: float, approved_by: str = "agent") -> str:
    """Approve an expense invoice after review. Validates amount matches."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT amount FROM invoices WHERE id = $1 AND status = 'pending'",
        invoice_id,
    )
    if not row:
        return f"Invoice {invoice_id} not found or not in pending status."
    if float(row["amount"]) != amount:
        return f"Amount mismatch: invoice is ${row['amount']}, approval for ${amount}."
    result = await pool.execute(
        """UPDATE invoices SET status = 'approved', processed_at = now(), processed_by = $2
           WHERE id = $1""",
        invoice_id,
        approved_by,
    )
    return f"Expense {invoice_id} approved for ${amount} by {approved_by}."
