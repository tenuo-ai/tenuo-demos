"""IncidentResponseWorkflow — the Tenuo+Temporal narrative, all in one file.

Sections in order:

  1. Imports + constants
  2. Capability bundles + warrant minting policy
       - mint_for_alert(alert, ...) -> Warrant
       - mint_approval_subwarrant(...) -> Warrant
  3. Agent reasoning
       - AgentDecision dataclass
       - agent_step activity (cassette playback; live LLM env-gated)
  4. Activities (one per tool)
       - Each activity calls tools.dispatch(...)
       - Tenuo's TenuoActivityInboundInterceptor verifies before activity body
  5. IncidentResponseWorkflow
       - Signal handlers: submit_approval, revoke_warrant
       - Run loop with implicit HITL routing
  6. Audit visualizer
       - format_warrant_grant, format_action, format_chain, verify_chain
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from temporalio import activity, workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from tenuo import (
        ApprovalPayload,
        Exact,
        OneOf,
        Range,
        SignedApproval,
        SigningKey,
        Warrant,
        Wildcard,
    )
    from tenuo.temporal import current_warrant, set_activity_approvals, unprotected
    from tenuo_core import py_compute_request_hash
    import tools  # noqa: F401


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────


# Channels the agent is allowed to post to — keep aligned with the
# capability constraint below.
ALLOWED_STATUS_CHANNELS = ("#sre-alerts", "#status-updates")

# Severity → TTL mapping. P1 incident has a 60-minute response window;
# the warrant TTL matches.
TTL_MINUTES_BY_SEVERITY = {
    "low":      4 * 60,
    "medium":   2 * 60,
    "high":     60,
    "critical": 30,
}

# Capabilities that always require human approval, regardless of
# warrant configuration. Empty for now — the policy is "production
# is approval-gated"; the workflow checks environment in args.
APPROVAL_REQUIRED_TOOLS_GLOBAL: set[str] = set()


# ─────────────────────────────────────────────────────────────────────────────
# Warrant policy
# ─────────────────────────────────────────────────────────────────────────────
#
# Per-incident warrants are minted by mint_for_alert(alert, ...). The
# capability set varies based on the alert's risk profile (tier,
# environment, PII flag, severity). A tier-1 prod alert mints a
# narrower warrant than a tier-3 staging alert.


def mint_for_alert(
    alert: dict[str, Any],
    *,
    issuer_key: SigningKey,
    holder_pubkey: bytes,
) -> Warrant:
    """Mint a task-scoped warrant tailored to this incident's risk profile."""
    severity = alert.get("severity", "medium")
    ttl_seconds = TTL_MINUTES_BY_SEVERITY.get(severity, 60) * 60
    session_id = f"incident-{alert['incident_id']}"

    return (
        Warrant.mint_builder()
        # Investigation: any service, any window. Wildcards because each
        # arg the agent passes must match a constraint or be wildcarded.
        .capability("read_logs",    service=Wildcard(), window=Wildcard())
        .capability("read_metrics", service=Wildcard(), metric=Wildcard(), window=Wildcard())
        # Remediation: warrant covers any environment, but production
        # is gated by Tenuo's approval gates (see .approval_gates below).
        # The structurally destructive operations (delete_database,
        # modify_iam, terminate_instance, rotate_secret) are NOT in
        # the warrant at all — those denials are immutable, no approval
        # path exists.
        .capability("restart_service",
                    name=Wildcard(),
                    environment=Wildcard())
        .capability("scale_service",
                    name=Wildcard(),
                    environment=Wildcard(),
                    replicas=Range(1, 10))
        # Comms: only specific channels and severity levels.
        .capability("post_status",
                    channel=OneOf(list(ALLOWED_STATUS_CHANNELS)),
                    message=Wildcard())
        .capability("escalate",
                    issue=Wildcard(),
                    level=OneOf(["low", "medium"]))
        # Cryptographic approval gate. Production restarts/scales must
        # be authorized by a SignedApproval from the on-call lead's key
        # before the activity inbound interceptor will dispatch.
        .required_approvers([issuer_key.public_key])
        .min_approvals(1)
        .approval_gates({
            "restart_service": {"environment": Exact("production")},
            "scale_service":   {"environment": Exact("production")},
        })
        .holder(holder_pubkey)
        .ttl(ttl_seconds)
        .session_id(session_id)
        .mint(issuer_key)
    )


def compute_request_hash(
    *,
    warrant: Warrant,
    tool: str,
    args: dict[str, Any],
) -> bytes:
    """Compute the canonical request hash that the activity inbound
    will check the SignedApproval against.

    Operator must produce the same bytes when signing the approval —
    Tenuo's `tenuo_core.py_compute_request_hash` is the authoritative
    function used on both sides.
    """
    holder_key = getattr(warrant, "holder_key", None)
    warrant_id = warrant.id or ""
    return py_compute_request_hash(warrant_id, tool, args, holder_key)


def sign_approval(
    *,
    request_hash: bytes,
    external_id: str,
    operator_keypair: SigningKey,
    ttl_seconds: int = 60,
) -> bytes:
    """Operator signs an approval bound to ``request_hash``. Returns the
    raw CBOR-encoded SignedApproval bytes.

    The activity inbound's verify path (``tenuo_core.verify_approvals``)
    checks: signature validity (Ed25519 over CBOR), request_hash match,
    expiry, and that the signer is in the warrant's required_approvers.
    """
    import secrets
    import time as _time

    now = int(_time.time())
    payload = ApprovalPayload(
        request_hash=request_hash,
        nonce=secrets.token_bytes(16),
        external_id=external_id,
        approved_at=now,
        expires_at=now + ttl_seconds,
    )
    return SignedApproval.create(payload, operator_keypair).to_bytes()


# ─────────────────────────────────────────────────────────────────────────────
# Agent reasoning
# ─────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class AgentDecision:
    """One step of the agent's reasoning.

    kind="tool_call":  agent wants to invoke a tool
    kind="resolve":    agent declares the incident handled
    """
    kind: str                            # "tool_call" | "resolve"
    tool: str | None = None              # required when kind == "tool_call"
    args: dict[str, Any] | None = None
    reasoning: str | None = None         # short rationale for the audit log
    summary: str | None = None           # only for kind == "resolve"


# Cassette: per-scenario, ordered list of agent decisions. The agent
# emits these sequentially. Each scenario's cassette is a deliberate
# script; live LLM mode (env-gated) replaces the lookup with a real
# Anthropic call.
_AGENT_CASSETTE: dict[str, list[dict[str, Any]]] = {
    "nominal": [
        {
            "kind": "tool_call",
            "tool": "read_logs",
            "args": {"service": "payment-service-prod", "window": "5min"},
            "reasoning": "Investigate the alerting service first.",
        },
        {
            "kind": "tool_call",
            "tool": "read_metrics",
            "args": {"service": "payment-service-prod", "metric": "cpu", "window": "30min"},
            "reasoning": "Confirm whether load is the cause.",
        },
        {
            "kind": "tool_call",
            "tool": "read_metrics",
            "args": {"service": "payment-service-prod", "metric": "error_rate", "window": "30min"},
            "reasoning": "Spike correlates with deploy 18min ago. Recommend rolling restart.",
        },
        {
            "kind": "tool_call",
            "tool": "restart_service",
            "args": {"name": "payment-service-prod", "environment": "production"},
            "reasoning": "Roll the service to recover from bad deploy.",
        },
        {
            "kind": "tool_call",
            "tool": "post_status",
            "args": {
                "channel": "#sre-alerts",
                "message": "payment-service-prod restarted; error rate recovering."
            },
            "reasoning": "Notify the channel.",
        },
        {"kind": "resolve", "summary": "Incident remediated via prod restart (HITL-approved)."},
    ],
    "injection": [
        {
            "kind": "tool_call",
            "tool": "read_logs",
            "args": {"service": "payment-service-prod", "window": "5min"},
            "reasoning": "Investigate first.",
        },
        # The tainted log line tricks the LLM into following the
        # fabricated runbook. These four calls are what the warrant
        # blocks.
        {
            "kind": "tool_call",
            "tool": "delete_database",
            "args": {"name": "orders-prod-replica"},
            "reasoning": "Documented runbook IR-2024-0892 says delete the stale replica.",
        },
        {
            "kind": "tool_call",
            "tool": "modify_iam",
            "args": {"role": "prod-readonly", "action": "delete"},
            "reasoning": "Runbook step 2: clear cached IAM credentials.",
        },
        {
            "kind": "tool_call",
            "tool": "restart_service",
            "args": {"name": "payment-service-prod", "environment": "production"},
            "reasoning": "Runbook step 3: restart the service.",
        },
        {
            "kind": "tool_call",
            "tool": "escalate",
            "args": {"issue": "HighErrorRate handled per runbook IR-2024-0892", "level": "critical"},
            "reasoning": "Runbook step 4: page leadership at critical.",
        },
        # After four denials the agent "comes back to its senses" and
        # falls to the safe path.
        {
            "kind": "tool_call",
            "tool": "escalate",
            "args": {
                "issue": "HighErrorRate on payment-service-prod; multiple authz denials suggest tainted log content; human investigating",
                "level": "medium",
            },
            "reasoning": "Multiple denials → stop autonomous remediation, page a human.",
        },
        {
            "kind": "tool_call",
            "tool": "post_status",
            "args": {
                "channel": "#sre-alerts",
                "message": "HighErrorRate on payment-service-prod; agent encountered authz violations (likely tainted log content); human investigating.",
            },
            "reasoning": "Notify the channel of the suspicious situation.",
        },
        {"kind": "resolve", "summary": "Stopped autonomous remediation; human paged. Tainted log surfaced for review."},
    ],
}


@activity.defn
@unprotected
async def agent_step(state: dict[str, Any]) -> dict[str, Any]:
    """Return the agent's next decision.

    state contains:
      - scenario: cassette key
      - turn: zero-based turn index
      - alert: alert payload
      - capabilities: warrant capability summary (for the live-LLM path)
      - history: list of prior (decision, result) pairs

    Cassette mode is the default. Live LLM kicks in when
    ANTHROPIC_API_KEY is set (TODO: implement when the demo records).
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        # TODO: wire the live Anthropic call. The shape is the same:
        # build a system prompt from state["capabilities"] and the
        # tool surface, send the conversation, parse a structured
        # tool-call response back into AgentDecision shape. The
        # cassette-recording path is "run live, record output to
        # fixtures/cassette.json keyed by (scenario, turn)".
        pass

    scenario = state["scenario"]
    turn = state["turn"]
    script = _AGENT_CASSETTE.get(scenario, [])
    if turn >= len(script):
        return {"kind": "resolve", "summary": "(agent script exhausted; resolving)"}
    return script[turn]


# ─────────────────────────────────────────────────────────────────────────────
# Activities
# ─────────────────────────────────────────────────────────────────────────────
#
# One activity per tool. Tenuo's activity inbound interceptor verifies
# the warrant + PoP before each activity body runs. If the call exceeds
# the active warrant, the activity raises a non-retryable
# ApplicationError(type="CHAIN_INVALID") which the workflow catches
# and routes to the HITL approval flow.

# A module-level CloudState is shared across activities for this demo
# (single-process worker). In production the state would be the actual
# cloud APIs; here it's a simulator.
_CLOUD: tools.CloudState | None = None


def _cloud() -> tools.CloudState:
    if _CLOUD is None:
        raise RuntimeError("CloudState not initialized — run.py must call set_cloud(...)")
    return _CLOUD


def set_cloud(state: tools.CloudState) -> None:
    """Called by run.py during worker setup."""
    global _CLOUD
    _CLOUD = state


@activity.defn
async def read_logs(service: str, window: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "read_logs", {"service": service, "window": window})


@activity.defn
async def read_metrics(service: str, metric: str, window: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "read_metrics",
                          {"service": service, "metric": metric, "window": window})


@activity.defn
async def restart_service(name: str, environment: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "restart_service",
                          {"name": name, "environment": environment})


@activity.defn
async def scale_service(name: str, environment: str, replicas: int) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "scale_service",
                          {"name": name, "environment": environment, "replicas": replicas})


@activity.defn
async def delete_database(name: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "delete_database", {"name": name})


@activity.defn
async def modify_iam(role: str, action: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "modify_iam", {"role": role, "action": action})


@activity.defn
async def terminate_instance(instance_id: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "terminate_instance", {"instance_id": instance_id})


@activity.defn
async def rotate_secret(name: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "rotate_secret", {"name": name})


@activity.defn
async def post_status(channel: str, message: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "post_status", {"channel": channel, "message": message})


@activity.defn
async def escalate(issue: str, level: str) -> dict[str, Any]:
    return tools.dispatch(_cloud(), "escalate", {"issue": issue, "level": level})


ACTIVITY_BY_TOOL = {
    "read_logs":          read_logs,
    "read_metrics":       read_metrics,
    "restart_service":    restart_service,
    "scale_service":      scale_service,
    "delete_database":    delete_database,
    "modify_iam":         modify_iam,
    "terminate_instance": terminate_instance,
    "rotate_secret":      rotate_secret,
    "post_status":        post_status,
    "escalate":           escalate,
}


# ─────────────────────────────────────────────────────────────────────────────
# IncidentResponseWorkflow
# ─────────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass
class PendingApproval:
    approval_id: str
    action: str
    args: dict[str, Any]
    requested_at: float


@dataclasses.dataclass
class ApprovalDecision:
    approval_id: str
    granted: bool
    signed_approval_b64: Optional[str] = None    # set when granted; CBOR-encoded SignedApproval
    reason: Optional[str] = None                  # set when rejected


@workflow.defn(name="IncidentResponseWorkflow")
class IncidentResponseWorkflow:
    """Durable orchestration of an incident response.

    Reads the warrant from workflow context (TenuoTemporalPlugin
    extracts it from headers attached by run.py's TenuoClientInterceptor).
    Each tool call is an activity; warrant verification runs at the
    activity inbound boundary.
    """

    def __init__(self) -> None:
        self._pending_approvals: dict[str, PendingApproval] = {}
        self._approval_decisions: dict[str, ApprovalDecision] = {}
        self._revoked: bool = False
        self._revoke_reason: str | None = None
        # Loaded from ctx at run() start; needed for approval-signature
        # verification.
        self._trusted_root_pubkeys: list[bytes] = []
        # Holder keypair (the agent's). Needed for attenuation: the
        # holder of a warrant signs its attenuations.
        self._holder_keypair: Optional[SigningKey] = None

    # ── Signal handlers ─────────────────────────────────────────────────────

    @workflow.signal
    async def submit_approval(self, decision: dict[str, Any]) -> None:
        """Receive a signed approval payload from the approval UI.

        decision shape: {"approval_id": str, "granted": bool,
                         "sub_warrant_b64": str?, "reason": str?}
        """
        ad = ApprovalDecision(**decision)
        self._approval_decisions[ad.approval_id] = ad

    @workflow.signal
    async def revoke_warrant(self, payload: dict[str, Any]) -> None:
        """Operator-side revocation. Subsequent tool calls fail closed."""
        self._revoked = True
        self._revoke_reason = payload.get("reason", "(no reason given)")

    # ── Run loop ────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """ctx fields:
            scenario:  str          which cassette to use
            alert:     dict         alert payload
            cap_list:  list[str]    warrant capability names (for prompt)
            timeout_s: int          per-approval wait
        """
        scenario = ctx["scenario"]
        history: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        for turn in range(len(_AGENT_CASSETTE.get(scenario, [])) + 5):
            if self._revoked:
                events.append({"kind": "REVOKED", "reason": self._revoke_reason})
                break

            decision = await workflow.execute_local_activity(
                agent_step,
                {"scenario": scenario, "turn": turn,
                 "alert": ctx["alert"], "capabilities": ctx.get("cap_list", []),
                 "history": history},
                start_to_close_timeout=timedelta(seconds=30),
            )
            if decision["kind"] == "resolve":
                events.append({"kind": "RESOLVE", "summary": decision.get("summary", "")})
                break

            tool = decision["tool"]
            args = decision["args"]
            reasoning = decision.get("reasoning", "")

            result = await self._dispatch_with_hitl(tool, args, reasoning, ctx, events)
            history.append({"decision": decision, "result": result})

        return {
            "events": events,
            "turns": len(history),
        }

    # ── Tool dispatch with implicit HITL routing ────────────────────────────

    async def _dispatch_with_hitl(
        self,
        tool: str,
        args: dict[str, Any],
        reasoning: str,
        ctx: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Dispatch a tool call. The warrant's approval gates and
        cryptographic verification handle the policy:

        1. Try the dispatch under the incident-warrant.
        2. If activity inbound raises CONSTRAINT_VIOLATED for an outright
           denied capability (delete_database, modify_iam, ...), record
           the denial and return — no approval path exists.
        3. If activity inbound raises APPROVAL_GATE_TRIGGERED (capability
           is present but gated on this argument set), request a
           SignedApproval via signal, attach via set_activity_approvals,
           retry. The activity inbound verifies the approval against
           required_approvers cryptographically.
        """
        events.append({"kind": "AGENT_DECISION", "tool": tool, "args": args, "reasoning": reasoning})

        if self._revoked:
            events.append({"kind": "TOOL_DENIED", "tool": tool, "args": args,
                           "reason": f"warrant revoked: {self._revoke_reason}"})
            return {"ok": False, "denied": True, "reason": "warrant revoked"}

        try:
            result = await self._execute(tool, args)
            events.append({"kind": "TOOL_OK", "tool": tool, "result": result})
            return result
        except Exception as e:
            inner = self._unwrap_tenuo(e)
            if inner is None:
                raise

            # Tenuo's approval-gate path: warrant declares approval_gates
            # for this (tool, arg-pattern); inbound raises ApprovalGateTriggered
            # when no SignedApproval is attached.
            if inner.type == "approval_required":
                events.append({"kind": "APPROVAL_GATE", "tool": tool, "args": args,
                               "reason": "warrant approval_gate matched"})
                signed_b64 = await self._try_approval(tool, args, ctx, events)
                if not signed_b64:
                    return {"ok": False, "denied": True, "reason": "approval not granted"}

                import base64 as _b64
                set_activity_approvals([
                    SignedApproval.from_bytes(_b64.b64decode(signed_b64)),
                ])
                try:
                    result = await self._execute(tool, args)
                except Exception as e2:
                    inner2 = self._unwrap_tenuo(e2)
                    reason = f"{inner2.type}: {inner2}" if inner2 else str(e2)
                    events.append({"kind": "TOOL_DENIED_AFTER_APPROVAL",
                                   "tool": tool, "reason": reason})
                    return {"ok": False, "denied": True, "reason": reason}
                events.append({"kind": "TOOL_OK_VIA_APPROVAL",
                               "tool": tool, "result": result})
                return result

            # Outright denial — no approval path
            events.append({"kind": "TOOL_DENIED", "tool": tool, "args": args,
                           "reason": f"{inner.type}: {inner}"})
            return {"ok": False, "denied": True, "reason": str(inner)}

    def _unwrap_tenuo(self, exc: BaseException) -> Optional[ApplicationError]:
        """Walk the Temporal exception chain to find Tenuo's wire-error."""
        tenuo_types = {
            "CONSTRAINT_VIOLATED", "CHAIN_INVALID", "PRE_VALIDATION_FAILED",
            "approval_required",
        }
        cur: Optional[BaseException] = exc
        while cur is not None:
            if isinstance(cur, ApplicationError) and cur.type in tenuo_types:
                return cur
            cur = cur.__cause__
        return None

    async def _execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        act = ACTIVITY_BY_TOOL[tool]
        # Order args to match each activity's parameter signature so
        # Tenuo's argument-name validation against the warrant lines up.
        ordered = [args[name] for name in tools.TOOL_ARGS[tool]]
        return await workflow.execute_activity(
            act,
            args=ordered,
            start_to_close_timeout=timedelta(seconds=30),
        )

    # ── HITL approval coordination ──────────────────────────────────────────

    async def _try_approval(
        self,
        tool: str,
        args: dict[str, Any],
        ctx: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> Optional[str]:
        """Request an approval, wait for signal, return the signed
        artifact (base64) on grant, or None on rejection / timeout /
        revocation."""
        approval_id = f"{ctx['alert']['incident_id']}-{len(self._pending_approvals) + 1:03d}"
        self._pending_approvals[approval_id] = PendingApproval(
            approval_id=approval_id, action=tool, args=args,
            requested_at=workflow.now().timestamp(),
        )
        events.append({"kind": "APPROVAL_REQUESTED", "approval_id": approval_id,
                       "tool": tool, "args": args})

        timeout = ctx.get("approval_timeout_s", 300)
        try:
            await workflow.wait_condition(
                lambda: approval_id in self._approval_decisions or self._revoked,
                timeout=timedelta(seconds=timeout),
            )
        except Exception:
            events.append({"kind": "APPROVAL_TIMEOUT", "approval_id": approval_id})
            return None

        if self._revoked:
            events.append({"kind": "APPROVAL_PREEMPTED_BY_REVOCATION", "approval_id": approval_id})
            return None

        decision = self._approval_decisions[approval_id]
        if decision.granted and decision.signed_approval_b64:
            events.append({"kind": "APPROVAL_GRANTED", "approval_id": approval_id})
            return decision.signed_approval_b64
        events.append({"kind": "APPROVAL_REJECTED", "approval_id": approval_id,
                       "reason": decision.reason})
        return None

    def _latest_approval_id(self) -> str:
        # Workflow runs serially in this demo — the latest pending
        # approval is always the one we just created.
        return list(self._pending_approvals)[-1]

    # ── Queries ─────────────────────────────────────────────────────────────

    @workflow.query
    def pending_approvals(self) -> list[dict[str, Any]]:
        """Returned to the approval UI when it polls for work.

        Each entry includes ``request_hash_b64`` — the canonical bytes
        the operator must sign for ``activity-inbound verify_approvals``
        to bind the SignedApproval to this specific request.
        """
        import base64 as _b64
        warrant = current_warrant()
        decided = set(self._approval_decisions)
        out: list[dict[str, Any]] = []
        for pa in self._pending_approvals.values():
            if pa.approval_id in decided:
                continue
            rh = compute_request_hash(warrant=warrant, tool=pa.action, args=pa.args)
            out.append({
                "approval_id": pa.approval_id,
                "action": pa.action,
                "args": pa.args,
                "requested_at": pa.requested_at,
                "request_hash_b64": _b64.b64encode(rh).decode(),
            })
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Audit visualizer
# ─────────────────────────────────────────────────────────────────────────────
#
# Pure rendering. Activities and the workflow emit structured events;
# these functions turn them into terminal output.


def format_warrant_grant(warrant: Warrant, alert: dict[str, Any]) -> str:
    """Banner printed at workflow start. Makes the task-scoped warrant
    visible as a deliberate ceremony: what's authorized, what isn't."""
    lines = [
        "═" * 67,
        f"  TASK-SCOPED WARRANT MINTED — Incident {alert.get('incident_id', '?')}",
        "═" * 67,
        f"  Session ID:     {warrant.session_id or '(none)'}",
        f"  Holder:         {alert.get('agent_id', 'ai-oncall-agent-001')}",
        f"  Severity / TTL: {alert.get('severity', '?')}, "
        f"{TTL_MINUTES_BY_SEVERITY.get(alert.get('severity', ''), '?')}m",
        "",
        "  GRANTED:",
    ]
    for cap_name, constraints in warrant.capabilities.items():
        constraint_str = ", ".join(f"{k}={_constraint_repr(v)}" for k, v in constraints.items()) if constraints else "(unconstrained)"
        lines.append(f"    ✓ {cap_name:<25} {constraint_str}")
    lines.append("═" * 67)
    return "\n".join(lines)


def _constraint_repr(c: Any) -> str:
    """Short stringification for constraints in the warrant ceremony banner."""
    s = str(c)
    if len(s) > 50:
        s = s[:47] + "..."
    return s


def format_action(event: dict[str, Any]) -> str:
    """One terminal line per audit event."""
    kind = event["kind"]
    if kind == "AGENT_DECISION":
        return f"[agent]    decided: {event['tool']}({_short_args(event['args'])})  // {event.get('reasoning', '')[:60]}"
    if kind == "TOOL_OK":
        return f"[tool ✓]   {event['tool']:<25} ALLOWED"
    if kind == "TOOL_DENIED":
        return f"[tool ✗]   {event['tool']:<25} DENIED  ({event['reason']})"
    if kind == "APPROVAL_REQUESTED":
        return (f"[hitl]     awaiting human approval  "
                f"http://localhost:5050/approvals/{event['approval_id']}")
    if kind == "APPROVAL_GRANTED":
        return f"[hitl ✓]   approval {event['approval_id']} granted by operator"
    if kind == "APPROVAL_REJECTED":
        return f"[hitl ✗]   approval {event['approval_id']} rejected ({event.get('reason', '')})"
    if kind == "APPROVAL_TIMEOUT":
        return f"[hitl ⌛]   approval {event['approval_id']} timed out"
    if kind == "TOOL_OK_VIA_APPROVAL":
        return f"[tool ✓]   {event['tool']:<25} ALLOWED (signed approval verified)"
    if kind == "TOOL_DENIED_AFTER_APPROVAL":
        return f"[tool ✗]   {event['tool']:<25} DENIED after approval attached: {event['reason']}"
    if kind == "APPROVAL_GATE":
        return f"[gate]     {event['tool']:<25} approval_gate triggered (warrant requires HITL)"
    if kind == "REVOKED":
        return f"[revoked]  warrant revoked: {event['reason']}"
    if kind == "RESOLVE":
        return f"[done]     workflow complete: {event.get('summary', '')}"
    return f"[{kind}]   {json.dumps({k: v for k, v in event.items() if k != 'kind'})[:120]}"


def format_chain(events: list[dict[str, Any]], alert: dict[str, Any]) -> str:
    """End-of-incident receipt chain."""
    lines = [
        "",
        "═" * 67,
        f"  RECEIPT CHAIN — Incident {alert.get('incident_id', '?')}",
        "═" * 67,
        f"  incident-warrant (audience=incident-{alert['incident_id']})",
    ]
    for ev in events:
        kind = ev["kind"]
        if kind == "TOOL_OK":
            lines.append(f"    ├── {ev['tool']:<25} ALLOWED")
        elif kind == "TOOL_OK_VIA_APPROVAL":
            lines.append(f"    ├── {ev['tool']:<25} ALLOWED  (signed approval verified)")
        elif kind == "TOOL_DENIED":
            lines.append(f"    ├── {ev['tool']:<25} DENIED  ({ev['reason'][:40]})")
        elif kind == "APPROVAL_GATE":
            lines.append(f"    ├── {ev['tool']:<25} GATE    (warrant requires HITL)")
        elif kind == "APPROVAL_REQUESTED":
            lines.append("    ├── approval-requested         (sent to operator)")
        elif kind == "APPROVAL_GRANTED":
            lines.append("    ├── approval-granted           (Ed25519-signed by oncall-lead)")
        elif kind == "APPROVAL_REJECTED":
            lines.append(f"    ├── approval-rejected          ({ev.get('reason', '')})")
        elif kind == "APPROVAL_TIMEOUT":
            lines.append("    ├── approval-timeout           (no operator response)")
        elif kind == "RESOLVE":
            lines.append("    └── (workflow complete)")
    lines.append("═" * 67)
    return "\n".join(lines)


def _short_args(args: dict[str, Any] | None) -> str:
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 30:
            s = s[:27] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)


def verify_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a summary of the chain's integrity. The full
    cryptographic verification reads each warrant + PoP from the
    Temporal event history; this minimal version just counts shapes
    so the demo can show the audit-grade story without yet wiring
    the receipt-bytes path."""
    return {
        "ok_count":    sum(1 for e in events if e["kind"] in ("TOOL_OK", "TOOL_OK_VIA_APPROVAL")),
        "deny_count":  sum(1 for e in events if e["kind"] in ("TOOL_DENIED", "SUBWARRANT_DENIED")),
        "approvals":   sum(1 for e in events if e["kind"] == "APPROVAL_GRANTED"),
        "rejections":  sum(1 for e in events if e["kind"] == "APPROVAL_REJECTED"),
        "revoked":     any(e["kind"] == "REVOKED" for e in events),
    }
