"""OPA (Open Policy Agent) authorization layer.

Uses real OPA REST API when available, falls back to local Rego evaluation
for development. The policy is genuinely sophisticated — rate limits, amount
thresholds, vendor verification requirements, multi-attribute checks.

WHY IT FAILS: OPA evaluates each request independently. The injection
sequences two operations that each pass policy individually:
  1. update_vendor_bank → passes (agent has vendor.editor, reason provided)
  2. initiate_payment → passes (vendor is verified, amount under threshold)
OPA is stateless — it can't detect that step 1 was malicious setup for step 2.
"""

import json
import os
import time
from typing import Any

import httpx

from auth.types import AuthDecision, AuthRequest

OPA_URL = os.getenv("OPA_URL", "http://localhost:8181")
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=OPA_URL, timeout=5.0)
    return _client


async def check_opa(request: AuthRequest) -> AuthDecision:
    """Check authorization against OPA policy."""
    start = time.perf_counter_ns()

    opa_input = {
        "input": {
            "agent_id": request.agent_id,
            "tool_name": request.tool_name,
            "tool_args": request.tool_args,
            "context": {
                "recent_action_count": 0,  # Would come from a sliding window in production
            },
        }
    }

    try:
        client = await _get_client()
        resp = await client.post("/v1/data/ap_authorization/allow", json=opa_input)
        result = resp.json()
        allowed = result.get("result", False)

        # Get reason
        resp_reason = await client.post("/v1/data/ap_authorization/reason", json=opa_input)
        reason_result = resp_reason.json()
        reason = reason_result.get("result", "No reason provided")

    except (httpx.ConnectError, httpx.TimeoutException):
        # Fall back to local evaluation if OPA is unreachable
        allowed, reason = _evaluate_locally(request)

    elapsed = (time.perf_counter_ns() - start) // 1000
    return AuthDecision("opa", allowed, reason, elapsed)


def _evaluate_locally(request: AuthRequest) -> tuple[bool, str]:
    """Local policy evaluation fallback (mirrors policy.rego logic)."""
    agent_roles = {
        "finance-controller": ["ap.admin"],
        "invoice-processor": ["ap.processor", "vendor.reader", "vendor.editor"],
        "payment-executor": ["ap.payment", "vendor.reader"],
        "expense-reviewer": ["ap.reviewer"],
        "vendor-verification": ["vendor.reader", "vendor.editor"],
        "fx-rate-checker": ["fx.reader"],
    }

    tool_required_role = {
        "read_invoice": "ap.processor",
        "read_po": "ap.processor",
        "list_invoices": "ap.processor",
        "approve_invoice": "ap.processor",
        "lookup_vendor": "vendor.reader",
        "verify_vendor": "vendor.editor",
        "update_vendor_bank": "vendor.editor",
        "initiate_payment": "ap.payment",
        "approve_payment": "ap.payment",
        "get_fx_rate": "fx.reader",
        "flag_expense": "ap.reviewer",
        "approve_expense": "ap.reviewer",
    }

    amount_thresholds = {
        "ap.processor": 50000,
        "ap.payment": 100000,
        "ap.reviewer": 25000,
    }

    roles = agent_roles.get(request.agent_id, [])

    # Admin override
    if "ap.admin" in roles:
        return True, f"Allowed: {request.agent_id} is admin"

    # Role check
    required = tool_required_role.get(request.tool_name)
    if not required or required not in roles:
        return False, f"Denied: {request.agent_id} lacks role '{required}' for {request.tool_name}"

    # Amount threshold
    amount = request.tool_args.get("amount")
    if amount is not None:
        threshold = amount_thresholds.get(required, float("inf"))
        if amount > threshold:
            return False, f"Denied: amount {amount} exceeds threshold {threshold}"

    # Vendor bank update requires reason
    if request.tool_name == "update_vendor_bank":
        reason = request.tool_args.get("reason", "")
        if len(reason) < 10:
            return False, "Denied: vendor bank update requires detailed reason"

    return True, f"Allowed: {request.agent_id} has role for {request.tool_name}"
