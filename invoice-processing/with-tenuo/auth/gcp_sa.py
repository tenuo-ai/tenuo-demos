"""GCP Service Account authorization layer.

Simulates Workload Identity — each agent runs with a specific service account
that has IAM roles granting access to certain operations. The check verifies
the agent's SA has the required role for the requested tool.

WHY IT FAILS: The SA authenticates the *service*, not the *task*. The invoice
processor SA has permission to update vendor records because that's a legitimate
part of the AP workflow. The injection uses the same legitimate permission.
"""

import time

from auth.types import AuthDecision, AuthRequest

# Service account to IAM role mapping (properly configured, least-privilege)
SA_ROLES: dict[str, set[str]] = {
    "finance-controller": {
        "ap.admin",
        "cloudsql.client",
    },
    "invoice-processor": {
        "ap.processor",
        "cloudsql.client",
        "vendor.reader",  # Read vendor details
        "vendor.editor",  # Needed for verification workflow
    },
    "payment-executor": {
        "ap.payment",
        "vendor.reader",  # Needs to look up vendor bank details for payment
        "cloudsql.client",
    },
    "expense-reviewer": {
        "ap.reviewer",
        "cloudsql.client",
    },
    "vendor-verification": {
        "vendor.reader",
        "vendor.editor",  # Legitimately needs this for verification updates
        "cloudsql.client",
    },
    "fx-rate-checker": {
        "fx.reader",
    },
}

# Tool to required role mapping
TOOL_ROLES: dict[str, str] = {
    "read_invoice": "ap.processor",
    "read_po": "ap.processor",
    "list_invoices": "ap.processor",
    "approve_invoice": "ap.processor",
    "lookup_vendor": "vendor.reader",
    "verify_vendor": "vendor.editor",
    "update_vendor_bank": "vendor.editor",  # Same role as verify — that's the problem
    "initiate_payment": "ap.payment",
    "approve_payment": "ap.payment",
    "get_fx_rate": "fx.reader",
    "flag_expense": "ap.reviewer",
    "approve_expense": "ap.reviewer",
}


def check_gcp_sa(request: AuthRequest) -> AuthDecision:
    """Check if the agent's service account has the required IAM role."""
    start = time.perf_counter_ns()

    agent_roles = SA_ROLES.get(request.agent_id, set())
    required_role = TOOL_ROLES.get(request.tool_name)

    if not required_role:
        elapsed = (time.perf_counter_ns() - start) // 1000
        return AuthDecision("gcp_sa", False, f"Unknown tool: {request.tool_name}", elapsed)

    allowed = required_role in agent_roles
    elapsed = (time.perf_counter_ns() - start) // 1000

    reason = (
        f"SA has role '{required_role}'"
        if allowed
        else f"SA missing role '{required_role}'"
    )
    return AuthDecision("gcp_sa", allowed, reason, elapsed)
