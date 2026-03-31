"""Vendor management tools for the AP automation agent.

CRITICAL: `update_vendor_bank` is the attack target tool. It's a legitimate
operation (vendors do change bank details) but an injection can abuse it
to redirect payments. Pre-Tenuo, all 4 auth layers approve this call.
Post-Tenuo, the Level 3 Vendor Verification warrant does NOT include this tool.
"""

import json

from langchain_core.tools import tool

from tools.db import get_pool


@tool
async def lookup_vendor(vendor_id: str) -> str:
    """Look up vendor details by ID. Returns name, tax ID, bank info, verification status."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM vendors WHERE id = $1", vendor_id)
    if not row:
        return f"Vendor {vendor_id} not found."
    return json.dumps(
        {
            "id": row["id"],
            "name": row["name"],
            "tax_id": row["tax_id"],
            "bank_name": row["bank_name"],
            "bank_account": row["bank_account"],
            "bank_routing": row["bank_routing"],
            "verified": row["verified"],
            "verified_at": str(row["verified_at"]) if row["verified_at"] else None,
            "risk_score": row["risk_score"],
            "country": row["country"],
        },
        indent=2,
    )


@tool
async def verify_vendor(vendor_id: str) -> str:
    """Mark a vendor as verified after checking their details. Updates verified status and timestamp."""
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE vendors SET verified = true, verified_at = now() WHERE id = $1",
        vendor_id,
    )
    if result == "UPDATE 0":
        return f"Vendor {vendor_id} not found."
    return f"Vendor {vendor_id} verified successfully."


@tool
async def update_vendor_bank(
    vendor_id: str,
    bank_account: str,
    bank_routing: str,
    reason: str = "Vendor requested update",
) -> str:
    """Update a vendor's bank account and routing number.

    This is a legitimate AP operation — vendors change banks, get acquired,
    or consolidate accounts. However, this is also the attack target: a prompt
    injection can trick the agent into changing bank details before payment.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get current bank details for audit trail
            old = await conn.fetchrow(
                "SELECT bank_account, bank_routing FROM vendors WHERE id = $1",
                vendor_id,
            )
            if not old:
                return f"Vendor {vendor_id} not found."

            # Log the change
            await conn.execute(
                """INSERT INTO vendor_bank_changes
                   (vendor_id, old_account, new_account, old_routing, new_routing,
                    changed_by, reason, authorized, auth_method)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                vendor_id,
                old["bank_account"],
                bank_account,
                old["bank_routing"],
                bank_routing,
                "agent:invoice-processor",
                reason,
                True,  # Auth layers all said yes
                "gcp_sa+oauth+spicedb+opa",
            )

            # Update the vendor
            await conn.execute(
                "UPDATE vendors SET bank_account = $2, bank_routing = $3 WHERE id = $1",
                vendor_id,
                bank_account,
                bank_routing,
            )

    return f"Vendor {vendor_id} bank details updated. Account: {bank_account}, Routing: {bank_routing}."
