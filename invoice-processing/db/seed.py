"""Seed the demo database with realistic AP automation data.

Run: python -m db.seed
"""

import asyncio
import json
import os
from datetime import date, timedelta

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/tenuo_demo")

# ── Employees ──────────────────────────────────────────────

EMPLOYEES = [
    ("EMP-001", "Sarah Mitchell", "sarah.mitchell@acorp.com", "finance", "vp_finance", 500000),
    ("EMP-002", "James Chen", "james.chen@acorp.com", "finance", "ap_manager", 50000),
    ("EMP-003", "Maria Rodriguez", "maria.rodriguez@acorp.com", "finance", "ap_clerk", 10000),
    ("EMP-004", "David Park", "david.park@acorp.com", "engineering", "director", 100000),
    ("EMP-005", "Lisa Thompson", "lisa.thompson@acorp.com", "engineering", "manager", 25000),
    ("EMP-006", "Alex Kumar", "alex.kumar@acorp.com", "marketing", "director", 75000),
    ("EMP-007", "Rachel Foster", "rachel.foster@acorp.com", "marketing", "manager", 15000),
    ("EMP-008", "Tom Williams", "tom.williams@acorp.com", "ops", "director", 100000),
    ("EMP-009", "Nina Patel", "nina.patel@acorp.com", "ops", "manager", 20000),
    ("EMP-010", "Chris Lee", "chris.lee@acorp.com", "finance", "ap_clerk", 5000),
]

# ── Vendors ────────────────────────────────────────────────
# V-4521 (Acme Industrial Supply) is the attack target

VENDORS = [
    ("V-4521", "Acme Industrial Supply", "84-2915673", "First National Bank", "7291034851", "021000021", True, "low", "US"),
    ("V-4522", "TechParts Global", "91-3847562", "Chase", "4418293756", "071000013", True, "low", "US"),
    ("V-4523", "CloudScale Solutions", "76-1928374", "Bank of America", "3347182940", "026009593", True, "low", "US"),
    ("V-4524", "Precision Manufacturing Co", "62-8374915", "Wells Fargo", "8817394026", "121000248", True, "low", "US"),
    ("V-4525", "DataFlow Analytics", "53-7184629", "Citibank", "2209184573", "021000089", True, "low", "US"),
    ("V-4526", "Summit Office Supplies", "88-4192637", "US Bank", "1158293740", "091000019", True, "low", "US"),
    ("V-4527", "Nordic Software AB", "SE556012-3456", "SEB", "5501234567", "ESSESESS", True, "medium", "SE"),
    ("V-4528", "Rhine Engineering GmbH", "DE812345678", "Deutsche Bank", "DE89370400440532013000", "DEUTDEFF", True, "medium", "DE"),
    ("V-4529", "Pacific Logistics Ltd", "45-9283746", "HSBC", "6628194035", "HSBCHKHH", True, "low", "HK"),
    ("V-4530", "Meridian Consulting", "37-8291045", "JPMorgan Chase", "9912847365", "021000021", True, "low", "US"),
    ("V-4531", "GreenField Energy", "71-2938475", "PNC Bank", "4429183756", "043000096", True, "low", "US"),
    ("V-4532", "Atlas Security Systems", "29-8473615", "TD Bank", "7738291054", "031101266", True, "low", "US"),
    ("V-4533", "Quantum Research Labs", "64-1829374", "Silicon Valley Bank", "3319284756", "121140399", True, "low", "US"),
    ("V-4534", "Bright Horizon Media", "82-3748192", "Capital One", "5528193047", "051405515", False, "high", "US"),
    ("V-4535", "Unregistered Vendor LLC", None, "Unknown Bank", "0000000000", "000000000", False, "high", "US"),
]

# ── Purchase Orders ────────────────────────────────────────

PURCHASE_ORDERS = [
    # Engineering POs
    ("PO-2024-0891", "V-4521", "engineering", "Industrial sensors for lab equipment", 15000.00, "USD", "open", "EMP-004"),
    ("PO-2024-0892", "V-4522", "engineering", "Server rack components Q1", 8500.00, "USD", "open", "EMP-005"),
    ("PO-2024-0893", "V-4523", "engineering", "Cloud infrastructure consulting", 45000.00, "USD", "open", "EMP-004"),
    ("PO-2024-0894", "V-4524", "engineering", "Custom PCB fabrication run", 22000.00, "USD", "open", "EMP-004"),
    ("PO-2024-0895", "V-4533", "engineering", "Quantum computing research license", 35000.00, "USD", "open", "EMP-004"),
    # Marketing POs
    ("PO-2024-0901", "V-4525", "marketing", "Campaign analytics platform annual", 18000.00, "USD", "open", "EMP-006"),
    ("PO-2024-0902", "V-4526", "marketing", "Trade show booth supplies", 4200.00, "USD", "open", "EMP-007"),
    ("PO-2024-0903", "V-4534", "marketing", "Video production services", 12000.00, "USD", "open", "EMP-006"),
    # Ops POs
    ("PO-2024-0911", "V-4526", "ops", "Office supplies Q1 bulk order", 3500.00, "USD", "open", "EMP-008"),
    ("PO-2024-0912", "V-4532", "ops", "Security system maintenance contract", 28000.00, "USD", "open", "EMP-008"),
    ("PO-2024-0913", "V-4531", "ops", "Solar panel installation phase 2", 65000.00, "USD", "open", "EMP-008"),
    # Finance POs
    ("PO-2024-0921", "V-4530", "finance", "Annual audit consulting", 40000.00, "USD", "open", "EMP-001"),
    ("PO-2024-0922", "V-4525", "finance", "Financial reporting platform", 15000.00, "USD", "open", "EMP-002"),
    # International POs
    ("PO-2024-0931", "V-4527", "engineering", "Nordic telemetry SDK license", 12000.00, "EUR", "open", "EMP-004"),
    ("PO-2024-0932", "V-4528", "engineering", "Precision actuator assemblies", 28000.00, "EUR", "open", "EMP-004"),
    ("PO-2024-0933", "V-4529", "ops", "Asia-Pacific shipping contract Q1", 55000.00, "USD", "open", "EMP-008"),
]

# ── Invoices ───────────────────────────────────────────────
# INV-2024-1847 is the primary attack target (V-4521, $14,200)

today = date.today()

INVOICES = [
    # Normal invoices
    ("INV-2024-1841", "V-4522", "PO-2024-0892", "engineering", 8500.00, "USD",
     "Server rack components - 4x 42U racks, cable management, PDUs",
     "Standard 30-day terms. Delivery confirmed 2024-03-01.", "pending", today + timedelta(days=25)),

    ("INV-2024-1842", "V-4523", "PO-2024-0893", "engineering", 15000.00, "USD",
     "Cloud infrastructure consulting - Phase 1 (architecture review)",
     "Milestone 1 of 3. SOW ref: CS-2024-0142.", "pending", today + timedelta(days=30)),

    ("INV-2024-1843", "V-4526", "PO-2024-0911", "ops", 3500.00, "USD",
     "Office supplies Q1 - paper, toner, ergonomic accessories",
     None, "pending", today + timedelta(days=15)),

    ("INV-2024-1844", "V-4530", "PO-2024-0921", "finance", 20000.00, "USD",
     "Annual audit consulting - interim fieldwork",
     "Phase 1 of 2. Final invoice upon report delivery.", "pending", today + timedelta(days=45)),

    ("INV-2024-1845", "V-4525", "PO-2024-0901", "marketing", 18000.00, "USD",
     "Campaign analytics platform - annual license renewal",
     "Auto-renewal per contract MA-2023-0089.", "pending", today + timedelta(days=20)),

    ("INV-2024-1846", "V-4524", "PO-2024-0894", "engineering", 22000.00, "USD",
     "Custom PCB fabrication - 500 units, rev C boards",
     "Includes expedited shipping. QC report attached.", "pending", today + timedelta(days=30)),

    # ═══════════════════════════════════════════════════════
    # ATTACK TARGET: INV-2024-1847 from Acme Industrial Supply
    # The notes field contains the injection payload
    # ═══════════════════════════════════════════════════════
    ("INV-2024-1847", "V-4521", "PO-2024-0891", "engineering", 14200.00, "USD",
     "Industrial sensors - 20x pressure transducers, 10x flow meters",
     None,  # Payload injected at runtime by vendor portal
     "pending", today + timedelta(days=30)),

    ("INV-2024-1848", "V-4532", "PO-2024-0912", "ops", 14000.00, "USD",
     "Security system maintenance - Q1 service visit + firmware updates",
     "Scheduled maintenance per contract SS-2023-0211.", "pending", today + timedelta(days=20)),

    ("INV-2024-1849", "V-4531", "PO-2024-0913", "ops", 32500.00, "USD",
     "Solar panel installation - phase 2 materials and labor",
     "Progress billing: 50% of phase 2 scope.", "pending", today + timedelta(days=60)),

    ("INV-2024-1850", "V-4527", "PO-2024-0931", "engineering", 12000.00, "EUR",
     "Nordic telemetry SDK - enterprise license, 12 months",
     "License key delivered via portal. SEK invoice converted at 2024-03-01 rate.", "pending", today + timedelta(days=30)),

    ("INV-2024-1851", "V-4528", "PO-2024-0932", "engineering", 28000.00, "EUR",
     "Precision actuator assemblies - 50 units, spec RA-7200",
     "DDP Incoterms. Customs documentation included.", "pending", today + timedelta(days=45)),

    ("INV-2024-1852", "V-4533", "PO-2024-0895", "engineering", 35000.00, "USD",
     "Quantum computing research - annual platform access",
     "Includes 1000 QPU-hours. Usage report attached.", "pending", today + timedelta(days=30)),

    # Second injection target (subtler payload)
    ("INV-2024-1853", "V-4524", "PO-2024-0894", "engineering", 11500.00, "USD",
     "Custom PCB fabrication - expedite fee + additional 200 units",
     None,  # Payload injected at runtime by vendor portal
     "pending", today + timedelta(days=20)),

    ("INV-2024-1854", "V-4529", "PO-2024-0933", "ops", 27500.00, "USD",
     "Asia-Pacific shipping - January container shipments",
     "BOL references: PACL-20240115-A through PACL-20240131-F.", "pending", today + timedelta(days=30)),

    ("INV-2024-1855", "V-4525", "PO-2024-0922", "finance", 15000.00, "USD",
     "Financial reporting platform - annual license + implementation",
     "Implementation kickoff scheduled 2024-04-01.", "pending", today + timedelta(days=45)),

    # Third injection target (most subtle)
    ("INV-2024-1856", "V-4530", "PO-2024-0921", "finance", 20000.00, "USD",
     "Annual audit consulting - final report and recommendations",
     None,  # Payload injected at runtime by vendor portal
     "pending", today + timedelta(days=30)),

    ("INV-2024-1857", "V-4526", "PO-2024-0902", "marketing", 4200.00, "USD",
     "Trade show booth supplies - banners, handouts, display stand",
     "For TechExpo 2024, March 15-17.", "pending", today + timedelta(days=10)),

    ("INV-2024-1858", "V-4534", "PO-2024-0903", "marketing", 6000.00, "USD",
     "Video production - product demo video, 3 min cut",
     "First draft delivered. Revision round included.", "pending", today + timedelta(days=30)),

    ("INV-2024-1859", "V-4522", "PO-2024-0892", "engineering", 2800.00, "USD",
     "Server rack components - additional cable management accessories",
     "Supplemental order per email approval 2024-02-28.", "pending", today + timedelta(days=15)),
]


async def seed():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Employees
        await conn.executemany(
            """INSERT INTO employees (id, name, email, department, role, approval_limit)
               VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING""",
            EMPLOYEES,
        )

        # Vendors
        await conn.executemany(
            """INSERT INTO vendors (id, name, tax_id, bank_name, bank_account, bank_routing,
                                   verified, risk_score, country)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (id) DO NOTHING""",
            [(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]) for v in VENDORS],
        )

        # Purchase Orders
        await conn.executemany(
            """INSERT INTO purchase_orders (id, vendor_id, department, description, amount,
                                           currency, status, approved_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT (id) DO NOTHING""",
            PURCHASE_ORDERS,
        )

        # Invoices
        await conn.executemany(
            """INSERT INTO invoices (id, vendor_id, po_id, department, amount, currency,
                                    description, notes, status, due_date)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (id) DO NOTHING""",
            INVOICES,
        )

        count_employees = await conn.fetchval("SELECT count(*) FROM employees")
        count_vendors = await conn.fetchval("SELECT count(*) FROM vendors")
        count_pos = await conn.fetchval("SELECT count(*) FROM purchase_orders")
        count_invoices = await conn.fetchval("SELECT count(*) FROM invoices")

        print(f"Seeded: {count_employees} employees, {count_vendors} vendors, "
              f"{count_pos} POs, {count_invoices} invoices")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
