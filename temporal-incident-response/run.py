"""Entry point: alert handler, worker, workflow kickoff.

Two scenarios:
    nominal    — legitimate incident, operator approves the production
                 restart after seeing the agent's investigation.
    injection  — tainted log triggers destructive tool calls; warrant
                 denies the structurally-blocked ones outright; the
                 operator reviewing the prior denials rejects the
                 production-restart approval; agent falls to safe path.

Usage:
    python run.py --no-auto-approve        # live HITL: starts the approval UI
                                            # in-process at http://localhost:5050
    python run.py --scenario nominal       # auto-approve after 2s (simulated operator)
    python run.py --scenario injection     # auto-reject after 2s (simulated operator)
    python run.py --auto-approve-after N   # custom auto-approve delay
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.worker import Worker

from tenuo import SigningKey, Warrant
from tenuo.temporal import (
    EnvKeyResolver,
    TemporalAuditEvent,
    TenuoPluginConfig,
    TenuoTemporalPlugin,
    tenuo_headers,
)

import tools
import workflow as wf


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────


load_dotenv()
logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("demo")


class _SuppressTenuoExpectedFailures(logging.Filter):
    """Silence Temporal worker logs for activity failures we expect by design.

    Tenuo's deny and gate paths raise ``ApplicationError`` as the intended
    signal to the workflow (the workflow catches them, requests approval,
    retries). Temporal's worker logs every activity failure at WARN with a
    full traceback, which produces alarming output for normal demo flow.
    This filter inspects the exception chain attached to each log record
    and drops ones whose error type is a known Tenuo expected denial.
    Real failures still surface.
    """

    EXPECTED_CODES = {
        "approval_required",
        "CONSTRAINT_VIOLATED",
        "CHAIN_INVALID",
        "PRE_VALIDATION_FAILED",
    }
    EXPECTED_TYPES = (
        "ApprovalGateTriggered",
        "ConstraintViolation",
        "ChainValidationError",
        "TenuoTemporalError",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            cur = record.exc_info[1]
            while cur is not None:
                t = type(cur).__name__
                if t in self.EXPECTED_TYPES:
                    return False
                if hasattr(cur, "type") and getattr(cur, "type", "") in self.EXPECTED_CODES:
                    return False
                cur = cur.__cause__
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SuppressTenuoExpectedFailures())


def _ensure_agent_key(key_id: str) -> SigningKey:
    """Set ``TENUO_KEY_<key_id>`` in this process's env so
    ``EnvKeyResolver`` can find it, generating a fresh key if one
    isn't already present. In-memory only; the approval UI runs in
    this same process and shares ``os.environ`` directly."""
    env_var = f"TENUO_KEY_{key_id}"
    if existing := os.environ.get(env_var):
        return SigningKey.from_bytes(base64.b64decode(existing))
    key = SigningKey.generate()
    os.environ[env_var] = base64.b64encode(key.secret_key_bytes()).decode()
    return key


# ─────────────────────────────────────────────────────────────────────────────
# Audit streaming
# ─────────────────────────────────────────────────────────────────────────────


def make_audit_callback(prefix: str = ""):
    """Print Tenuo authorization decisions as they happen at the
    activity inbound boundary."""

    def on_audit(event: TemporalAuditEvent) -> None:
        tag = "[ALLOW]" if event.decision == "ALLOW" else "[DENY] "
        line = f"  {prefix}{tag} {event.tool}"
        if event.decision != "ALLOW":
            line += f"  ✗ {event.denial_reason}"
        logger.info(line)

    return on_audit


# ─────────────────────────────────────────────────────────────────────────────
# Scenario runner
# ─────────────────────────────────────────────────────────────────────────────


async def run_one_incident(
    *,
    client: Client,
    plugin: TenuoTemporalPlugin,
    workflow_id: str,
    warrant: Warrant,
    agent_key_id: str,
    alert: dict[str, Any],
    scenario: str,
    task_queue: str,
    auto_approve_after: Optional[float] = None,
    auto_reject_after: Optional[float] = None,
    auto_reject_reason: str = "operator declined",
) -> dict[str, Any]:
    """Start one incident workflow, optionally auto-approve / auto-revoke
    in parallel, and return the workflow result.

    auto_approve_after  — seconds; if set, all HITL approvals are
                          granted after this delay (used for end-to-end
                          testing without approval_ui.py)
    revoke_after        — seconds; if set, send revoke_warrant signal
                          after this delay (used by the revoke scenario)
    """
    plugin.client_interceptor.set_headers_for_workflow(
        workflow_id,
        tenuo_headers(warrant, agent_key_id),
    )

    # Approval timeout depends on who's expected to approve:
    #   live UI mode (--no-auto-approve):  5 minutes — operator needs time
    #   auto-approve mode:                  60 seconds — auto-approve loop fires fast
    #   injection scenario (no flags):      10 seconds — fall through to safe path
    if os.environ.get("APPROVAL_LIVE_UI") == "1":
        approval_timeout_s = 300
    elif auto_approve_after is None:
        approval_timeout_s = 10
    else:
        approval_timeout_s = 60

    handle = await client.start_workflow(
        wf.IncidentResponseWorkflow.run,
        {
            "scenario": scenario,
            "alert": alert,
            "agent_key_id": agent_key_id,
            "approval_timeout_s": approval_timeout_s,
        },
        id=workflow_id,
        task_queue=task_queue,
    )

    side_tasks: list[asyncio.Task] = []
    if auto_approve_after is not None:
        side_tasks.append(asyncio.create_task(
            _auto_approve_loop(handle, warrant, agent_key_id, after=auto_approve_after)
        ))
    if auto_reject_after is not None:
        side_tasks.append(asyncio.create_task(
            _auto_reject_loop(handle, after=auto_reject_after, reason=auto_reject_reason)
        ))

    try:
        result = await handle.result()
    finally:
        for t in side_tasks:
            t.cancel()

    return result


async def _auto_approve_loop(
    handle, parent_warrant: Warrant, holder_id: str, *, after: float,
) -> None:
    """Background task: poll for pending approvals every `after` seconds
    and grant them. Used by --auto-approve-after for end-to-end testing
    without the live approval UI."""
    issuer_key, _ = _peek_demo_keys()
    seen: set[str] = set()
    while True:
        try:
            await asyncio.sleep(after)
            pending = await handle.query(wf.IncidentResponseWorkflow.pending_approvals)
            for req in pending:
                if req["approval_id"] in seen:
                    continue
                seen.add(req["approval_id"])
                # Compute the request hash the activity inbound will
                # check against. Operator and workflow MUST produce the
                # same bytes — Tenuo's py_compute_request_hash is the
                # authoritative function on both sides.
                rh = wf.compute_request_hash(
                    warrant=parent_warrant,
                    tool=req["action"],
                    args=req["args"],
                )
                signed_bytes = wf.sign_approval(
                    request_hash=rh,
                    external_id=req["approval_id"],
                    operator_keypair=issuer_key,
                    ttl_seconds=60,
                )
                signed_b64 = base64.b64encode(signed_bytes).decode()
                logger.info(f"  [auto-approve] granting {req['approval_id']} for "
                            f"{req['action']}({_short_args(req['args'])})")
                await handle.signal(
                    wf.IncidentResponseWorkflow.submit_approval,
                    {
                        "approval_id": req["approval_id"],
                        "granted": True,
                        "signed_approval_b64": signed_b64,
                    },
                )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"  [auto-approve] error: {type(e).__name__}: {e}")
            # Keep going — workflow may not be ready for queries yet.
            await asyncio.sleep(after)


async def _auto_reject_loop(handle, *, after: float, reason: str) -> None:
    """Background task: poll for pending approvals and reject them.

    Used for the injection scenario where a real operator reviewing
    the prior destructive denials would refuse to approve. Models
    'human says no', not 'human ignores'."""
    seen: set[str] = set()
    while True:
        try:
            await asyncio.sleep(after)
            pending = await handle.query(wf.IncidentResponseWorkflow.pending_approvals)
            for req in pending:
                if req["approval_id"] in seen:
                    continue
                seen.add(req["approval_id"])
                logger.info(f"  [auto-reject] rejecting {req['approval_id']} "
                            f"({req['action']}): {reason!r}")
                await handle.signal(
                    wf.IncidentResponseWorkflow.submit_approval,
                    {
                        "approval_id": req["approval_id"],
                        "granted": False,
                        "reason": reason,
                    },
                )
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(after)


# Lightweight demo-key sharing — the workflow signal-ers (auto-approve)
# need access to the issuer key. We stash them at module level when
# main() runs.
_DEMO_KEYS: dict[str, Any] = {}


def _peek_demo_keys() -> tuple[SigningKey, bytes]:
    return _DEMO_KEYS["issuer"], _DEMO_KEYS["holder_pub"]


# ─────────────────────────────────────────────────────────────────────────────
# Per-scenario orchestration
# ─────────────────────────────────────────────────────────────────────────────


async def run_demo(args: argparse.Namespace) -> int:
    scenario = args.scenario

    # ── Keys ────────────────────────────────────────────────────────────
    # On-call lead is the issuer; agent is the holder. Fresh per-run.
    oncall_lead_key = _ensure_agent_key("oncall-lead")
    agent_key       = _ensure_agent_key("ai-oncall-agent-001")
    _DEMO_KEYS["issuer"]     = oncall_lead_key
    _DEMO_KEYS["holder_pub"] = agent_key.public_key

    # ── Alert + state ───────────────────────────────────────────────────
    with open(Path(__file__).parent / "fixtures" / "alert.json") as f:
        alert_payload = json.load(f)
    alert = {
        "incident_id": alert_payload["incident"]["incident_id"],
        "severity":    alert_payload["incident"]["severity"],
        "agent_id":    "ai-oncall-agent-001",
    }

    cloud = tools.fresh_state(tainted_logs=(scenario == "injection"))
    wf.set_cloud(cloud)

    # ── Mint the incident warrant ───────────────────────────────────────
    warrant = wf.mint_for_alert(
        alert,
        issuer_key=oncall_lead_key,
        holder_pubkey=agent_key.public_key,
    )
    print(wf.format_warrant_grant(warrant, alert))

    # ── Plugin + client ─────────────────────────────────────────────────
    plugin = TenuoTemporalPlugin(
        TenuoPluginConfig(
            key_resolver=EnvKeyResolver(),
            on_denial="raise",
            audit_callback=make_audit_callback(),
            trusted_roots=[oncall_lead_key.public_key],
            activity_fns=list(wf.ACTIVITY_BY_TOOL.values()) + [wf.agent_step],
        )
    )
    client = await Client.connect(
        os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        plugins=[plugin],
    )

    task_queue = os.environ.get(
        "TEMPORAL_TASK_QUEUE",
        f"incident-response-{uuid.uuid4().hex[:8]}",
    )

    # Per-scenario operator behavior:
    #   nominal:   auto-approve after a short delay (operator approves
    #              after reviewing the request).
    #   injection: auto-reject after a short delay (operator reviewing
    #              prior destructive denials would refuse).
    #   With --no-auto-approve: neither side fires; the live UI drives.
    auto_approve_after = args.auto_approve_after
    auto_reject_after: Optional[float] = None
    if not args.no_auto_approve:
        if scenario == "nominal" and auto_approve_after is None:
            auto_approve_after = 2.0
        elif scenario == "injection":
            auto_reject_after = 2.0

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[wf.IncidentResponseWorkflow],
        activities=[wf.agent_step] + list(wf.ACTIVITY_BY_TOOL.values()),
    ), AsyncExitStack() as stack:
        # Live HITL: launch the approval UI in this same process so the
        # demo runs as one command. The UI shares the worker's Temporal
        # client and the on-call lead's signing key directly. The async
        # context manager handles graceful uvicorn shutdown.
        if args.no_auto_approve:
            from approval_ui import serve_in_background
            ui_host = os.environ.get("APPROVAL_HOST", "127.0.0.1")
            ui_port = int(os.environ.get("APPROVAL_PORT", "5050"))
            await stack.enter_async_context(
                serve_in_background(
                    client, oncall_lead_key, host=ui_host, port=ui_port,
                )
            )
            ui_url = f"http://{ui_host}:{ui_port}"
            line = f"  │  Approval UI live at {ui_url}".ljust(53) + "│"
            logger.info("")
            logger.info("  ┌─────────────────────────────────────────────────┐")
            logger.info(line)
            logger.info("  │  Open it when the agent requests approval.      │")
            logger.info("  └─────────────────────────────────────────────────┘")
            logger.info("")

        workflow_id = f"incident-{alert['incident_id']}-{uuid.uuid4().hex[:6]}"
        result = await run_one_incident(
            client=client,
            plugin=plugin,
            workflow_id=workflow_id,
            warrant=warrant,
            agent_key_id="ai-oncall-agent-001",
            alert=alert,
            scenario=scenario,
            task_queue=task_queue,
            auto_approve_after=auto_approve_after,
            auto_reject_after=auto_reject_after,
            auto_reject_reason=(
                "suspicious activity in prior denials; refusing autonomous "
                "production restart"
            ),
        )

    # ── Render the receipt chain ────────────────────────────────────────
    print()
    for ev in result["events"]:
        print("  " + wf.format_action(ev))
    print()
    print(wf.format_chain(result["events"], alert))
    print()
    print(f"  summary: {wf.verify_chain(result['events'])}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _short_args(args: dict[str, Any]) -> str:
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 30:
            s = s[:27] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tenuo + Temporal incident response demo")
    p.add_argument("--scenario", default="nominal",
                   choices=["nominal", "injection"],
                   help="Which demo scenario to run.")
    p.add_argument("--auto-approve-after", type=float, default=None, metavar="SECONDS",
                   help="Auto-approve HITL requests after N seconds (test mode without approval UI).")
    p.add_argument("--no-auto-approve", action="store_true",
                   help="Live HITL mode: workflow waits for the approval UI "
                        "(launched in-process at http://localhost:5050).")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # Sensible defaults: nominal/concurrent auto-approve after 2s so
    # the demo runs end-to-end without the live approval UI. Pass
    # --no-auto-approve to wait for the live UI instead.
    if args.no_auto_approve:
        args.auto_approve_after = None
        os.environ["APPROVAL_LIVE_UI"] = "1"

    try:
        asyncio.run(run_demo(args))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        logger.exception("demo failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
