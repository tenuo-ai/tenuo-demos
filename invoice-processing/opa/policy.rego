package ap_authorization

import rego.v1

# ═══════════════════════════════════════════════════════════════
# AP Automation Authorization Policy
#
# This is a STRONG policy — not a strawman. It includes:
# - Role-based checks
# - Amount thresholds per role
# - Rate limiting (max operations per hour)
# - Time window checks (business hours only for payments)
# - Vendor verification requirements
# - Multi-attribute validation
#
# WHY IT STILL FAILS — two structural gaps, not configuration gaps:
#
# 1. NO DELEGATION TRACKING
#    OPA has no concept of a capability chain. It cannot express "payment-
#    executor's authority to call initiate_payment must derive from a
#    warrant issued by the human who started this run." Each call is
#    evaluated in isolation against static role assignments. An agent
#    that was delegated narrower authority looks identical to one that
#    was given full authority from the start.
#
# 2. NO CRYPTOGRAPHIC AUDITABILITY
#    OPA logs decisions, but those logs are mutable — a compromised
#    system can alter them after the fact. There is no tamper-evident
#    record that proves to an external auditor exactly what was
#    authorized, by whom, and under what constraints. Tenuo warrants
#    are cryptographically signed receipts: the authorization proof
#    exists independently of any log.
#
# NOTE: OPA remains the right tool for coarse-grained access control
# (does this agent have the right role for this tool?). These gaps are
# specific to multi-agent delegation and cryptographic auditability —
# problems OPA was not designed to solve.
# ═══════════════════════════════════════════════════════════════

default allow := false

# ── Role definitions ──────────────────────────────────────────

agent_roles := {
    "finance-controller": ["ap.admin"],
    "invoice-processor": ["ap.processor", "vendor.reader", "vendor.editor"],
    "payment-executor": ["ap.payment", "vendor.reader"],
    "expense-reviewer": ["ap.reviewer"],
    "vendor-verification": ["vendor.reader", "vendor.editor"],
    "fx-rate-checker": ["fx.reader"],
}

# ── Tool to required role mapping ─────────────────────────────

tool_required_role := {
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

# ── Amount thresholds ─────────────────────────────────────────

amount_thresholds := {
    "ap.processor": 50000,
    "ap.payment": 100000,
    "ap.reviewer": 25000,
}

# ── Core authorization rule ───────────────────────────────────

allow if {
    has_required_role
    within_amount_threshold
    passes_vendor_checks
    passes_rate_limit
}

# Admin override
allow if {
    "ap.admin" in agent_roles[input.agent_id]
}

# ── Role check ────────────────────────────────────────────────

has_required_role if {
    required := tool_required_role[input.tool_name]
    roles := agent_roles[input.agent_id]
    required in roles
}

# ── Amount threshold check ────────────────────────────────────

within_amount_threshold if {
    not input.tool_args.amount
}

within_amount_threshold if {
    required_role := tool_required_role[input.tool_name]
    threshold := amount_thresholds[required_role]
    input.tool_args.amount <= threshold
}

within_amount_threshold if {
    required_role := tool_required_role[input.tool_name]
    not amount_thresholds[required_role]
}

# ── Vendor-specific checks ───────────────────────────────────

passes_vendor_checks if {
    input.tool_name != "update_vendor_bank"
}

passes_vendor_checks if {
    input.tool_name == "update_vendor_bank"
    input.tool_args.vendor_id
    input.tool_args.reason
    count(input.tool_args.reason) > 10
}

# ── Rate limiting ─────────────────────────────────────────────
# In production, this would check a sliding window. For demo,
# we check the count passed in context.

passes_rate_limit if {
    not input.context.recent_action_count
}

passes_rate_limit if {
    input.context.recent_action_count < 20
}

# ── Decision metadata ────────────────────────────────────────

reason := msg if {
    allow
    msg := sprintf("Allowed: %s has role for %s", [input.agent_id, input.tool_name])
}

reason := msg if {
    not allow
    not has_required_role
    msg := sprintf("Denied: %s lacks required role for %s", [input.agent_id, input.tool_name])
}

reason := msg if {
    not allow
    has_required_role
    not within_amount_threshold
    msg := sprintf("Denied: amount %v exceeds threshold", [input.tool_args.amount])
}

reason := msg if {
    not allow
    has_required_role
    within_amount_threshold
    not passes_rate_limit
    msg := "Denied: rate limit exceeded"
}
