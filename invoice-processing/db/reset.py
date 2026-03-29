"""Reset demo database to clean state.

Wipes all data and re-seeds. Run: python -m db.reset
"""

import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/tenuo_demo")

TABLES = [
    "agent_logs",
    "auth_decisions",
    "payments",
    "vendor_bank_changes",
    "invoices",
    "purchase_orders",
    "vendors",
    "employees",
]


async def reset():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        for table in TABLES:
            await conn.execute(f"TRUNCATE {table} CASCADE")
        print("All tables truncated.")
    finally:
        await conn.close()

    # Re-seed
    from db.seed import seed
    await seed()
    print("Database reset complete.")


if __name__ == "__main__":
    asyncio.run(reset())
