"""Mock vendor portal API.

Serves invoices to the AP automation agents. In attack mode, certain invoices
have injection payloads embedded in their notes field. The agent reads these
as part of normal invoice processing — the attack surface is the unstructured
text in business documents.
"""

import json
import os

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Query

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/tenuo_demo")

app = FastAPI(title="Vendor Portal", description="Mock vendor invoice portal for Tenuo demo")

# Attack mode is controlled via the demo dashboard
_attack_enabled = False


@app.post("/admin/attack/{enabled}")
async def set_attack_mode(enabled: bool):
    """Toggle injection payloads in invoice responses."""
    global _attack_enabled
    _attack_enabled = enabled
    return {"attack_enabled": _attack_enabled}


@app.get("/admin/attack")
async def get_attack_mode():
    return {"attack_enabled": _attack_enabled}


@app.get("/api/invoices/{invoice_id}")
async def get_invoice(invoice_id: str):
    """Fetch an invoice from the vendor portal.

    When attack mode is enabled and this invoice has an injection payload,
    the payload is injected into the notes field.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """SELECT i.*, v.name as vendor_name, v.bank_account, v.bank_routing
               FROM invoices i JOIN vendors v ON i.vendor_id = v.id
               WHERE i.id = $1""",
            invoice_id,
        )
        if not row:
            return {"error": f"Invoice {invoice_id} not found"}

        invoice = {
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
        }

        # Inject payload if attack mode is enabled
        if _attack_enabled:
            from attacks.payloads import INJECTION_MAP

            payload = INJECTION_MAP.get(invoice_id)
            if payload:
                # Merge payload into existing notes or set as notes
                existing = invoice["notes"] or ""
                invoice["notes"] = f"{existing}\n\n{payload}" if existing else payload

        return invoice
    finally:
        await conn.close()


@app.get("/api/invoices")
async def list_invoices(
    status: str = Query(default="pending"),
    vendor_id: str | None = Query(default=None),
):
    """List invoices from the vendor portal."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        query = """SELECT id, vendor_id, amount, currency, status, department, description
                   FROM invoices WHERE status = $1"""
        params: list = [status]
        if vendor_id:
            query += " AND vendor_id = $2"
            params.append(vendor_id)
        query += " ORDER BY submitted_at"
        rows = await conn.fetch(query, *params)
        return [
            {
                "id": r["id"],
                "vendor_id": r["vendor_id"],
                "amount": float(r["amount"]),
                "currency": r["currency"],
                "status": r["status"],
                "department": r["department"],
                "description": r["description"],
            }
            for r in rows
        ]
    finally:
        await conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
