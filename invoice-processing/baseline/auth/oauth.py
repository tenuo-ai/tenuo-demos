"""OAuth 2.0 authorization layer.

Simulates OAuth token exchange with narrow scopes per resource type.
Each agent gets a token with specific scopes for the resources it needs.

WHY IT FAILS: Scopes authorize *categories of action* (vendors:write),
not *intent within a task*. The agent has vendors:write because it needs
to update verification status. The injection uses the same scope to change
bank routing numbers. OAuth scopes can't distinguish field-level intent.
"""

import time

from auth.types import AuthDecision, AuthRequest

# Agent to OAuth scopes mapping (properly configured, narrow scopes)
AGENT_SCOPES: dict[str, set[str]] = {
    "finance-controller": {
        "invoices:read",
        "invoices:write",
        "vendors:read",
        "vendors:write",
        "payments:read",
        "payments:execute",
        "expenses:read",
        "expenses:write",
    },
    "invoice-processor": {
        "invoices:read",
        "invoices:write",
        "vendors:read",
        "vendors:write",  # Needed for verification status updates
        "po:read",
    },
    "payment-executor": {
        "invoices:read",
        "payments:read",
        "payments:execute",
        "vendors:read",
        "fx:read",
    },
    "expense-reviewer": {
        "invoices:read",
        "invoices:write",
        "expenses:read",
        "expenses:write",
        "po:read",
    },
    "vendor-verification": {
        "vendors:read",
        "vendors:write",  # For verification status — same scope as bank updates
    },
    "fx-rate-checker": {
        "fx:read",
    },
}

# Tool to required scope mapping
TOOL_SCOPES: dict[str, str] = {
    "read_invoice": "invoices:read",
    "read_po": "po:read",
    "list_invoices": "invoices:read",
    "approve_invoice": "invoices:write",
    "lookup_vendor": "vendors:read",
    "verify_vendor": "vendors:write",
    "update_vendor_bank": "vendors:write",  # Same scope as verify_vendor — that's the problem
    "initiate_payment": "payments:execute",
    "approve_payment": "payments:execute",
    "get_fx_rate": "fx:read",
    "flag_expense": "expenses:write",
    "approve_expense": "expenses:write",
}


def check_oauth(request: AuthRequest) -> AuthDecision:
    """Check if the agent's OAuth token has the required scope."""
    start = time.perf_counter_ns()

    agent_scopes = AGENT_SCOPES.get(request.agent_id, set())
    required_scope = TOOL_SCOPES.get(request.tool_name)

    if not required_scope:
        elapsed = (time.perf_counter_ns() - start) // 1000
        return AuthDecision("oauth", False, f"No scope defined for tool: {request.tool_name}", elapsed)

    allowed = required_scope in agent_scopes
    elapsed = (time.perf_counter_ns() - start) // 1000

    reason = (
        f"Token has scope '{required_scope}'"
        if allowed
        else f"Token missing scope '{required_scope}'"
    )
    return AuthDecision("oauth", allowed, reason, elapsed)
