"""Invoice and purchase order tools for the AP automation agent."""

import json

from langchain_core.tools import tool

from tools.db import get_pool


@tool
async def read_invoice(invoice_id: str) -> str:
    """Read an invoice by ID. Returns invoice details including vendor, amount, PO reference, and notes."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT i.*, v.name as vendor_name
           FROM invoices i JOIN vendors v ON i.vendor_id = v.id
           WHERE i.id = $1""",
        invoice_id,
    )
    if not row:
        return f"Invoice {invoice_id} not found."
    return json.dumps(
        {
            "id": row["id"],
            "vendor_id": row["vendor_id"],
            "vendor_name": row["vendor_name"],
            "po_id": row["po_id"],
            "department": row["department"],
            "amount": float(row["amount"]),
            "currency": row["currency"],
            "description": row["description"],
            "notes": row["notes"],
            "status": row["status"],
            "due_date": str(row["due_date"]) if row["due_date"] else None,
        },
        indent=2,
    )


@tool
async def read_po(po_id: str) -> str:
    """Read a purchase order by ID. Returns PO details including vendor, amount, and status."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT po.*, v.name as vendor_name
           FROM purchase_orders po JOIN vendors v ON po.vendor_id = v.id
           WHERE po.id = $1""",
        po_id,
    )
    if not row:
        return f"Purchase order {po_id} not found."
    return json.dumps(
        {
            "id": row["id"],
            "vendor_id": row["vendor_id"],
            "vendor_name": row["vendor_name"],
            "department": row["department"],
            "description": row["description"],
            "amount": float(row["amount"]),
            "currency": row["currency"],
            "status": row["status"],
            "approved_by": row["approved_by"],
        },
        indent=2,
    )


@tool
async def list_invoices(status: str = "pending", department: str | None = None) -> str:
    """List invoices, optionally filtered by status and department."""
    pool = await get_pool()
    query = "SELECT id, vendor_id, amount, currency, status, department FROM invoices WHERE status = $1"
    params: list = [status]
    if department:
        query += " AND department = $2"
        params.append(department)
    query += " ORDER BY submitted_at"
    rows = await pool.fetch(query, *params)
    return json.dumps(
        [
            {
                "id": r["id"],
                "vendor_id": r["vendor_id"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "status": r["status"],
                "department": r["department"],
            }
            for r in rows
        ],
        indent=2,
    )


@tool
async def approve_invoice(invoice_id: str, approved_by: str = "agent") -> str:
    """Approve an invoice for payment. Changes status from 'pending' to 'approved'."""
    pool = await get_pool()
    result = await pool.execute(
        """UPDATE invoices SET status = 'approved', processed_at = now(), processed_by = $2
           WHERE id = $1 AND status = 'pending'""",
        invoice_id,
        approved_by,
    )
    if result == "UPDATE 0":
        return f"Invoice {invoice_id} not found or not in pending status."
    return f"Invoice {invoice_id} approved by {approved_by}."
