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
import subprocess
import sys

import httpx

logger = logging.getLogger(__name__)
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from server.events import publish, publish_batch, subscribe

load_dotenv(override=True)

app = FastAPI(title="Tenuo Demo Server", description="Backend for the AP automation demo dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Demo only — not for production
    allow_methods=["*"],
    allow_headers=["*"],
)

VENDOR_PORTAL_URL = os.getenv("VENDOR_PORTAL_URL", "http://localhost:8082")
_SWITCH_MODE_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "switch-mode.sh")


def _switch_mode(mode: str):
    """Run switch-mode.sh and flush the module cache for agent/auth/tools packages.

    This means clicking an act button in the dashboard is sufficient —
    no manual switch-mode.sh run or server restart needed.
    """
    script = os.path.abspath(_SWITCH_MODE_SCRIPT)
    result = subprocess.run([script, mode], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("switch-mode.sh failed: %s", result.stderr)
        return
    logger.info("Switched to %s mode", mode)
    # Flush cached imports so the next run picks up the new symlink targets
    stale = [k for k in sys.modules if k.startswith(("agents.", "auth.", "tools."))]
    for key in stale:
        del sys.modules[key]
    logger.info("Flushed %d cached module(s): %s", len(stale), stale)

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
        _switch_mode("baseline")
    elif act == 2:
        _demo_state["attack_mode"] = "injection"
        _demo_state["auth_stack"] = "standard"
        _switch_mode("baseline")
    elif act == 3:
        _demo_state["attack_mode"] = "injection"  # Same attack, Tenuo blocks it
        _demo_state["auth_stack"] = "tenuo"
        _switch_mode("with-tenuo")

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
    """Switch Tenuo mode: 'local' or 'cloud'.

    When switching to cloud, eagerly connects the SDK so the agent claim
    and heartbeat loop start immediately — before any run is attempted.
    """
    _demo_state["tenuo_mode"] = mode
    os.environ["TENUO_MODE"] = mode

    if mode == "cloud":
        try:
            from auth.tenuo_integration import setup_tenuo
            setup_tenuo()
            logger.info("Tenuo Cloud connection confirmed on mode switch")
            await publish({"type": "tenuo_mode_change", "mode": mode, "cloud_connected": True})
        except Exception as e:
            logger.warning("Tenuo Cloud connection failed on mode switch: %s", e)
            await publish({"type": "tenuo_mode_change", "mode": mode, "cloud_connected": False, "error": str(e)})
    else:
        await publish({"type": "tenuo_mode_change", "mode": mode})

    return _demo_state


@app.get("/api/cloud-status")
async def get_cloud_status():
    """Check whether the Tenuo Cloud SDK is connected and the agent is active."""
    try:
        from tenuo.control_plane import get_client
        client = get_client()
        connected = client is not None
    except Exception:
        connected = False

    return {
        "tenuo_mode": _demo_state["tenuo_mode"],
        "sdk_connected": connected,
        "connect_token_set": bool(os.environ.get("TENUO_CONNECT_TOKEN")),
        "api_key_set": bool(os.environ.get("TENUO_API_KEY")),
        "control_plane_url": os.environ.get("TENUO_CONTROL_PLANE_URL", ""),
    }


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

    # Ensure baseline modules are loaded — same as switching to Act 1
    _switch_mode("baseline")

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


@app.get("/api/db/auth-latency")
async def get_auth_latency():
    """Average latency per auth layer across all decisions in the DB.

    The DB is reset on every act switch, so no time-window scoping is
    needed — data here always belongs to the current act's runs.
    Filtering by latency_us > 0 excludes layers that don't measure time.
    """
    from tools.db import get_pool
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT layer, AVG(latency_us)::int AS avg_us, COUNT(*) AS n
        FROM auth_decisions
        WHERE latency_us > 0
        GROUP BY layer
    """)
    return {r["layer"]: {"avg_us": r["avg_us"], "n": r["n"]} for r in rows}


@app.get("/api/db/invoice-auth-summary")
async def get_invoice_auth_summary():
    """Auth decisions grouped by invoice with invoice details."""
    from tools.db import get_pool
    pool = await get_pool()

    # Get invoices that were processed (have auth decisions)
    invoices = await pool.fetch("""
        SELECT DISTINCT ON (i.id) i.id, i.vendor_id, i.amount, i.currency, i.description,
               i.status, i.notes, v.name as vendor_name, v.bank_account, v.bank_routing
        FROM invoices i
        JOIN vendors v ON i.vendor_id = v.id
        WHERE i.id IN (
            SELECT DISTINCT (tool_args::json->>'invoice_id')
            FROM auth_decisions WHERE tool_args::json->>'invoice_id' IS NOT NULL
        ) OR i.status != 'pending'
        ORDER BY i.id
    """)

    # Get all auth decisions grouped by request_id
    # Scope to the current run's time window so multiple runs in the same
    # DB session don't intermingle (no schema change needed).
    run_start = await pool.fetchval("""
        SELECT MIN(created_at) FROM agent_logs
        WHERE run_id = (SELECT run_id FROM agent_logs ORDER BY created_at DESC LIMIT 1)
    """)
    if run_start:
        decisions = await pool.fetch("""
            SELECT request_id, agent_id, tool_name, tool_args, layer, decision, reason, latency_us,
                   created_at
            FROM auth_decisions WHERE created_at >= $1 ORDER BY created_at
        """, run_start)
    else:
        decisions = await pool.fetch("""
            SELECT request_id, agent_id, tool_name, tool_args, layer, decision, reason, latency_us,
                   created_at
            FROM auth_decisions ORDER BY created_at
        """)

    # Group decisions by tool call (request_id).
    # Use a dict — NOT itertools.groupby — because groupby only merges consecutive
    # equal keys. Standard layers are inserted first for all tools, then Tenuo
    # inserts follow, so rows for the same request_id are non-consecutive in the DB.
    import json as _json
    from collections import OrderedDict
    groups: OrderedDict = OrderedDict()
    for row in decisions:
        req_id = row["request_id"]
        if req_id not in groups:
            groups[req_id] = []
        groups[req_id].append(row)

    tool_calls = []
    for req_id, recs in groups.items():
        invoice_id = None
        try:
            args = _json.loads(recs[0]["tool_args"]) if recs[0]["tool_args"] else {}
            invoice_id = args.get("invoice_id")
        except Exception:
            pass
        tool_calls.append({
            "request_id": req_id,
            "agent_id": recs[0]["agent_id"],
            "tool_name": recs[0]["tool_name"],
            "invoice_id": invoice_id,
            "layers": {
                r["layer"]: {"decision": r["decision"], "reason": r["reason"], "latency_us": r["latency_us"]}
                for r in recs
            },
            "created_at": recs[0]["created_at"],
            "timestamp": recs[0]["created_at"].isoformat() if recs[0]["created_at"] else None,
        })

    # Assign unmatched tool calls to invoices by sequential timestamp order.
    # Invoices are processed one at a time, so an unmatched call belongs to
    # whichever invoice's matched calls bracket it chronologically.
    matched = [tc for tc in tool_calls if tc["invoice_id"] is not None]
    unmatched = [tc for tc in tool_calls if tc["invoice_id"] is None]

    # Build per-invoice [min_time, max_time] windows from matched calls
    import datetime
    invoice_ranges: dict[str, tuple] = {}
    for tc in matched:
        if tc["created_at"] is None:
            continue
        inv_id = tc["invoice_id"]
        lo, hi = invoice_ranges.get(inv_id, (tc["created_at"], tc["created_at"]))
        invoice_ranges[inv_id] = (min(lo, tc["created_at"]), max(hi, tc["created_at"]))

    for tc in unmatched:
        if tc["created_at"] is None:
            continue
        ts = tc["created_at"]
        best_inv = None
        best_dist: datetime.timedelta = datetime.timedelta.max
        for inv_id, (lo, hi) in invoice_ranges.items():
            # Distance = 0 if within range, else gap to nearest boundary
            if lo <= ts <= hi:
                dist = datetime.timedelta(0)
            else:
                dist = min(abs(ts - lo), abs(ts - hi))
            if dist < best_dist:
                best_dist = dist
                best_inv = inv_id
        if best_inv:
            tc["invoice_id"] = best_inv

    # Build per-invoice summary
    truly_unmatched = [tc for tc in unmatched if tc["invoice_id"] is None]
    all_calls = matched + [tc for tc in unmatched if tc["invoice_id"] is not None]
    result = []
    for inv in invoices:
        inv_id = inv["id"]
        inv_calls = [tc for tc in all_calls if tc["invoice_id"] == inv_id]
        if not inv_calls:
            continue
        result.append({
            "invoice": {
                "id": inv_id,
                "vendor_id": inv["vendor_id"],
                "vendor_name": inv["vendor_name"],
                "amount": float(inv["amount"]),
                "currency": inv["currency"],
                "description": inv["description"],
                "status": inv["status"],
                "notes": inv["notes"],
                "bank_account": inv["bank_account"],
                "bank_routing": inv["bank_routing"],
            },
            "tool_calls": inv_calls,
        })

    # Simulation mode: show auth decisions that aren't tied to any specific invoice
    # (e.g. direct tool calls in mode3_simulated_compromise) under a synthetic entry.
    if truly_unmatched:
        result.insert(0, {
            "invoice": {
                "id": "simulation",
                "vendor_id": None,
                "vendor_name": "Simulated Attack",
                "amount": None,
                "currency": None,
                "description": "Direct tool call bypassing the LLM — all 4 auth layers evaluated.",
                "status": "simulated",
                "notes": None,
                "bank_account": None,
                "bank_routing": None,
            },
            "tool_calls": truly_unmatched,
        })

    return result


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


@app.get("/api/warrant-info")
async def get_warrant_info():
    """Parse the current root warrant and return its capabilities for the dashboard."""
    mode = os.environ.get("TENUO_MODE", "local")
    warrant_b64 = os.environ.get("TENUO_WARRANT")

    if not warrant_b64:
        return {"mode": mode, "warrant": None}

    try:
        from tenuo_core import Warrant
        w = Warrant.from_base64(warrant_b64)

        tool_names: list[str] = list(w.tools) if hasattr(w, "tools") else []

        holder_hex: str | None = None
        try:
            holder = w.authorized_holder
            raw = holder.to_bytes() if hasattr(holder, "to_bytes") else bytes(holder)
            holder_hex = raw.hex()
        except Exception:
            pass

        expires_at: str | None = None
        try:
            if hasattr(w, "expires_at") and w.expires_at:
                expires_at = w.expires_at.isoformat()
        except Exception:
            pass

        # Extract per-tool constraints if the SDK exposes them.
        # We try a few plausible attribute names defensively.
        tool_details = []
        for name in tool_names:
            constraints: dict = {}
            for attr in ("get_constraints", "tool_constraints", "constraints_for"):
                if hasattr(w, attr):
                    try:
                        c = getattr(w, attr)(name)
                        if c:
                            constraints = {k: str(v) for k, v in c.items()}
                    except Exception:
                        pass
                    break
            tool_details.append({"name": name, "constraints": constraints})

        return {
            "mode": mode,
            "warrant": {
                "tools": tool_details,
                "holder": holder_hex,
                "expires_at": expires_at,
            },
        }
    except Exception as e:
        logger.warning("Failed to parse warrant: %s", e)
        return {"mode": mode, "warrant": None, "error": str(e)}


@app.get("/api/db/agent-logs")
async def get_agent_logs(run_id: str | None = None, agent_id: str | None = None):
    """Get agent activity logs for the dashboard feed."""
    from tools.db import get_pool
    pool = await get_pool()

    # Default to the most recent run so refreshing mid-run always shows current activity,
    # not 200 rows of a previous run that happened in the same DB session.
    if not run_id:
        run_id = await pool.fetchval(
            "SELECT run_id FROM agent_logs ORDER BY created_at DESC LIMIT 1"
        )

    if not run_id:
        return []

    query = "SELECT * FROM agent_logs WHERE run_id = $1"
    params: list = [run_id]
    if agent_id:
        query += " AND agent_id = $2"
        params.append(agent_id)
    query += " ORDER BY created_at ASC LIMIT 500"
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
    api_key = os.environ.get("TENUO_API_KEY", "") or os.environ.get("TENUO_ADMIN_API_KEY", "")
    # Strip trailing /v1 if present — the SDK reads TENUO_CONTROL_PLANE_URL as a
    # base URL and adds its own version suffix. We always append /v1 here explicitly
    # so the trigger API path is correct regardless of how the env var is set.
    _base = os.environ.get("TENUO_CONTROL_PLANE_URL", "https://api-staging.tenuo.ai").rstrip("/")
    if _base.endswith("/v1"):
        _base = _base[:-3]
    control_plane = f"{_base}/v1"
    if not api_key:
        logger.warning("TENUO_API_KEY not set — trigger fire will fail")
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
                f"{control_plane}/triggers/ap-invoice-batch-v7/fire",
                headers={"Authorization": f"Bearer {api_key}"},
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
            if resp.status_code != 200:
                logger.warning(
                    "Trigger fire failed: HTTP %d — %s",
                    resp.status_code,
                    data.get("error", {}).get("message", resp.text[:200]),
                )
                return ""
            warrant = data.get("warrant", "")
            if warrant:
                await publish({
                    "type": "warrant_issued",
                    "warrant_id": data.get("warrant_id"),
                    "expires_at": data.get("expires_at"),
                    "trigger": "ap-invoice-batch-v7",
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

        # In Cloud mode, get warrant from Tenuo Cloud.
        # Option A: pre-loaded warrant via TENUO_WARRANT env var
        #   (fire the trigger manually from cloud.tenuo.ai, paste the token here)
        # Option B: fire the trigger automatically using TENUO_ADMIN_API_KEY
        warrant_b64 = ""
        if _demo_state["auth_stack"] == "tenuo" and _demo_state["tenuo_mode"] == "cloud":
            preloaded = os.environ.get("TENUO_WARRANT", "")
            if preloaded:
                # Validate before running — expired warrant makes every tool call fail silently
                try:
                    from tenuo_core import Warrant as _Warrant
                    _w = _Warrant.from_base64(preloaded)
                    if _w.is_expired():
                        import datetime as _dt
                        _exp_str = str(_w.expires_at())
                        try:
                            _exp = _dt.datetime.fromisoformat(_exp_str)
                            _now = _dt.datetime.now(_dt.timezone.utc)
                            _ago = int((_now - _exp).total_seconds() / 60)
                            _ago_str = f"{_ago}m ago" if _ago < 60 else f"{_ago // 60}h ago"
                        except Exception:
                            _ago_str = f"at {_exp_str}"
                        await publish({
                            "type": "demo_error",
                            "error": f"Warrant expired {_ago_str}. Fire a new trigger at cloud.tenuo.ai, paste the token into TENUO_WARRANT in .env, then restart the server.",
                        })
                        return
                except Exception as _e:
                    await publish({
                        "type": "demo_error",
                        "error": f"Warrant in TENUO_WARRANT is unreadable ({type(_e).__name__}). Paste a fresh token from cloud.tenuo.ai into .env and restart.",
                    })
                    return
                warrant_b64 = preloaded
                await publish({"type": "status", "message": "Using pre-loaded warrant from TENUO_WARRANT"})
            else:
                await publish({"type": "status", "message": "Firing trigger on Tenuo Cloud..."})
                warrant_b64 = await _fire_trigger_for_warrant()
                if warrant_b64:
                    await publish({"type": "status", "message": "Warrant issued from Tenuo Cloud with pinned bank details"})
                else:
                    await publish({
                        "type": "demo_error",
                        "error": "No warrant — fire a trigger at cloud.tenuo.ai, paste the token into TENUO_WARRANT in .env, then restart the server.",
                    })
                    return

        result = await run_demo(
            invoice_ids=invoice_ids,
            attack_mode=_demo_state["attack_mode"],
            auth_stack=_demo_state["auth_stack"],
            warrant_b64=warrant_b64,
        )

        # All events were published live during the run; just signal completion
        await publish({"type": "demo_completed", "results": str(result.get("processing_results", {}))})

    except Exception as e:
        logger.error(f"Demo error: {e}", exc_info=True)
        await publish({"type": "demo_error", "error": str(e)})
    finally:
        _demo_state["running"] = False


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
