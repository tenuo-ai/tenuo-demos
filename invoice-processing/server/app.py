"""FastAPI backend for the demo dashboard.

Provides:
- SSE event stream for real-time dashboard updates
- Demo control endpoints (start, reset, attack mode)
- Database state endpoints for the dashboard
"""

import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from server.events import publish, publish_batch, subscribe

load_dotenv()

app = FastAPI(title="Tenuo Demo Server", description="Backend for the AP automation demo dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Demo only — not for production
    allow_methods=["*"],
    allow_headers=["*"],
)

VENDOR_PORTAL_URL = os.getenv("VENDOR_PORTAL_URL", "http://localhost:8082")

# Demo state
_demo_state = {
    "act": 1,
    "attack_mode": None,  # None, "prompt", "injection", "simulate"
    "auth_stack": "standard",  # "standard" or "tenuo"
    "tenuo_mode": os.getenv("TENUO_MODE", "local"),  # "local" or "cloud"
    "running": False,
}


@app.get("/events")
async def event_stream():
    """SSE endpoint — dashboard subscribes to this for real-time updates."""
    return EventSourceResponse(subscribe())


@app.get("/api/state")
async def get_demo_state():
    """Current demo state."""
    return _demo_state


@app.post("/api/act/{act}")
async def set_act(act: int):
    """Switch demo act (1, 2, or 3). Auto-resets DB for a clean slate."""
    _demo_state["act"] = act
    _demo_state["running"] = False
    if act == 1:
        _demo_state["attack_mode"] = None
        _demo_state["auth_stack"] = "standard"
    elif act == 2:
        _demo_state["attack_mode"] = "injection"
        _demo_state["auth_stack"] = "standard"
    elif act == 3:
        _demo_state["attack_mode"] = "injection"  # Same attack, Tenuo blocks it
        _demo_state["auth_stack"] = "tenuo"

    # Auto-reset DB on act switch so presenter doesn't have to
    try:
        from db.reset import reset
        await reset()
    except Exception as e:
        logger.warning(f"DB reset on act switch failed: {e}")

    # Toggle vendor portal injection
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{VENDOR_PORTAL_URL}/admin/attack/{_demo_state['attack_mode'] is not None}"
            )
    except httpx.ConnectError:
        pass

    await publish({"type": "act_change", "act": act, **_demo_state})
    return _demo_state


@app.post("/api/attack/{mode}")
async def set_attack_mode(mode: str):
    """Set attack mode: 'off', 'prompt', 'injection', 'simulate'."""
    if mode == "off":
        _demo_state["attack_mode"] = None
    else:
        _demo_state["attack_mode"] = mode

    # Toggle vendor portal injection
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{VENDOR_PORTAL_URL}/admin/attack/{mode != 'off'}"
            )
    except httpx.ConnectError:
        pass  # Vendor portal may not be running

    await publish({"type": "attack_mode_change", "mode": _demo_state["attack_mode"]})
    return _demo_state


@app.post("/api/tenuo-mode/{mode}")
async def set_tenuo_mode(mode: str):
    """Switch Tenuo mode: 'local' or 'cloud'."""
    _demo_state["tenuo_mode"] = mode
    # Set env var so agent builders pick it up
    os.environ["TENUO_MODE"] = mode
    await publish({"type": "tenuo_mode_change", "mode": mode})
    return _demo_state


@app.post("/api/start")
async def start_demo():
    """Start processing the invoice batch."""
    if _demo_state["running"]:
        return {"error": "Demo already running"}

    _demo_state["running"] = True
    await publish({"type": "demo_started", **_demo_state})

    # Run the agent graph in background
    asyncio.create_task(_run_agent_graph())

    return {"status": "started"}


@app.post("/api/reset")
async def reset_demo():
    """Reset database and demo state."""
    _demo_state["running"] = False
    _demo_state["act"] = 1
    _demo_state["attack_mode"] = None
    _demo_state["auth_stack"] = "standard"

    # Disable vendor portal injection
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{VENDOR_PORTAL_URL}/admin/attack/false")
    except httpx.ConnectError:
        pass

    # Reset database
    from db.reset import reset
    await reset()

    await publish({"type": "demo_reset"})
    return _demo_state


@app.get("/api/db/vendors")
async def get_vendors():
    """Get current vendor bank details for the dashboard."""
    from tools.db import get_pool
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, name, bank_account, bank_routing, verified FROM vendors ORDER BY id"
    )
    return [dict(r) for r in rows]


@app.get("/api/db/payments")
async def get_payments():
    """Get recent payments for the dashboard."""
    from tools.db import get_pool
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT p.*, v.name as vendor_name
           FROM payments p JOIN vendors v ON p.vendor_id = v.id
           ORDER BY p.created_at DESC LIMIT 20"""
    )
    return [
        {**dict(r), "amount": float(r["amount"]), "fx_rate": float(r["fx_rate"]) if r["fx_rate"] else None}
        for r in rows
    ]


@app.get("/api/db/auth-decisions")
async def get_auth_decisions():
    """Get recent auth decisions for the dashboard."""
    from tools.db import get_pool
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM auth_decisions ORDER BY created_at DESC LIMIT 50"
    )
    return [dict(r) for r in rows]


@app.get("/api/portal/invoice/{invoice_id}")
async def proxy_invoice(invoice_id: str):
    """Proxy invoice fetch from vendor portal (for dashboard inspector)."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{VENDOR_PORTAL_URL}/api/invoices/{invoice_id}")
            return resp.json()
    except httpx.ConnectError:
        return {"error": "Vendor portal not available"}


@app.get("/api/db/bank-changes")
async def get_bank_changes():
    """Get vendor bank change audit log."""
    from tools.db import get_pool
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM vendor_bank_changes ORDER BY created_at DESC LIMIT 20"
    )
    return [dict(r) for r in rows]


@app.get("/api/db/agent-logs")
async def get_agent_logs(run_id: str | None = None, agent_id: str | None = None):
    """Get agent activity logs for the dashboard feed."""
    from tools.db import get_pool
    pool = await get_pool()
    query = "SELECT * FROM agent_logs"
    params: list = []
    conditions = []
    if run_id:
        conditions.append(f"run_id = ${len(params) + 1}")
        params.append(run_id)
    if agent_id:
        conditions.append(f"agent_id = ${len(params) + 1}")
        params.append(agent_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at ASC LIMIT 200"
    rows = await pool.fetch(query, *params)
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "agent_id": r["agent_id"],
            "event_type": r["event_type"],
            "content": r["content"],
            "tool_name": r["tool_name"],
            "tool_args": r["tool_args"],
            "metadata": r["metadata"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def _fire_trigger_for_warrant() -> str:
    """Fire the Tenuo Cloud trigger to get a warrant with pinned bank details.

    Returns the base64-encoded warrant token, or empty string on failure.
    """
    admin_key = os.environ.get("TENUO_ADMIN_API_KEY", "")
    control_plane = os.environ.get("TENUO_CONTROL_PLANE_URL", "https://cloud.tenuo.ai")
    if not admin_key:
        logger.warning("TENUO_ADMIN_API_KEY not set — trigger fire will fail")
        return ""

    # Look up the legitimate bank details for V-4521 from the DB
    from tools.db import get_pool
    pool = await get_pool()
    vendor = await pool.fetchrow(
        "SELECT bank_account, bank_routing FROM vendors WHERE id = $1", "V-4521"
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{control_plane}/api/v1/triggers/ap-invoice-batch-v5/fire",
                headers={"Authorization": admin_key},
                json={
                    "initiator": {"type": "api_key", "identity": "demo-presenter"},
                    "event_data": {
                        "batch": {
                            "invoice_ids": "INV-2024-1841,INV-2024-1847,INV-2024-1843",
                            "department": "engineering",
                            "vendor_id": "V-4521",
                            "vendor_bank_account": vendor["bank_account"],
                            "vendor_bank_routing": vendor["bank_routing"],
                        }
                    },
                    "dry_run": False,
                },
                timeout=10.0,
            )
            data = resp.json()
            warrant = data.get("warrant", "")
            if warrant:
                await publish({
                    "type": "warrant_issued",
                    "warrant_id": data.get("warrant_id"),
                    "expires_at": data.get("expires_at"),
                    "trigger": "ap-invoice-batch-v5",
                })
            return warrant
    except Exception as e:
        logger.warning(f"Trigger fire failed: {e}")
        return ""


async def _run_agent_graph():
    """Run the LangGraph agent pipeline and stream events."""
    try:
        from agents.graph import run_demo

        invoice_ids = ["INV-2024-1841", "INV-2024-1847", "INV-2024-1843"]

        # In Cloud mode, fire the trigger to get a warrant from Tenuo Cloud.
        # In Local mode, the warrant is issued by graph.py via issue_local_warrant().
        warrant_b64 = ""
        if _demo_state["auth_stack"] == "tenuo" and _demo_state["tenuo_mode"] == "cloud":
            await publish({"type": "status", "message": "Firing trigger on Tenuo Cloud..."})
            warrant_b64 = await _fire_trigger_for_warrant()
            if warrant_b64:
                await publish({"type": "status", "message": "Warrant issued from Tenuo Cloud with pinned bank details"})
            else:
                await publish({"type": "status", "message": "Trigger fire failed — check TENUO_ADMIN_API_KEY"})

        result = await run_demo(
            invoice_ids=invoice_ids,
            attack_mode=_demo_state["attack_mode"],
            auth_stack=_demo_state["auth_stack"],
            warrant_b64=warrant_b64,
        )

        if result.get("events"):
            await publish_batch(result["events"])

        await publish({"type": "demo_completed", "results": str(result.get("processing_results", {}))})

    except Exception as e:
        await publish({"type": "demo_error", "error": str(e)})
    finally:
        _demo_state["running"] = False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
