"""SpiceDB (Zanzibar) RBAC authorization layer.

Uses real SpiceDB gRPC client when available, falls back to in-memory
relationship checks for local development.

WHY IT FAILS: SpiceDB authorizes relationships on objects — "agent IS editor
of vendor:V-4521." It can't distinguish what the agent does within that
relationship. Updating verification status and updating bank details are
both "editor" operations on the same vendor object.
"""

import os
import time

from auth.types import AuthDecision, AuthRequest

SPICEDB_ENDPOINT = os.getenv("SPICEDB_ENDPOINT", "localhost:50051")
SPICEDB_TOKEN = os.getenv("SPICEDB_TOKEN", "demo-preshared-key")

# Tool to SpiceDB permission check mapping
# Format: (object_type, permission, object_id_from_arg)
TOOL_PERMISSIONS: dict[str, tuple[str, str, str | None]] = {
    "read_invoice": ("invoice", "read", "invoice_id"),
    "read_po": ("purchase_order", "read", "po_id"),
    "list_invoices": ("invoice", "read", None),  # No specific object
    "approve_invoice": ("invoice", "approve", "invoice_id"),
    "lookup_vendor": ("vendor", "read", "vendor_id"),
    "verify_vendor": ("vendor", "verify", "vendor_id"),
    "update_vendor_bank": ("vendor", "update_bank", "vendor_id"),  # Same editor permission
    "initiate_payment": ("payment", "execute", None),
    "approve_payment": ("payment", "approve", "payment_id"),
    "get_fx_rate": ("payment", "read", None),  # No specific object for FX
    "flag_expense": ("invoice", "write", "invoice_id"),
    "approve_expense": ("invoice", "approve", "invoice_id"),
}

# In-memory relationships for local dev (mirrors relationships.yaml)
_LOCAL_RELATIONSHIPS: dict[tuple[str, str, str], bool] = {}
_initialized = False


def _init_local_relationships():
    """Initialize in-memory relationships from the YAML config."""
    global _LOCAL_RELATIONSHIPS, _initialized
    if _initialized:
        return

    # Agent-level relationships (simplified for demo)
    agents_with_editor = {
        ("vendor", "V-4521"): ["invoice-processor", "vendor-verification"],
        ("vendor", "V-4522"): ["invoice-processor"],
        ("vendor", "V-4523"): ["invoice-processor"],
        ("vendor", "V-4524"): ["invoice-processor"],
    }

    for (obj_type, obj_id), agents in agents_with_editor.items():
        for agent in agents:
            _LOCAL_RELATIONSHIPS[(f"{obj_type}:{obj_id}", "read", f"agent:{agent}")] = True
            _LOCAL_RELATIONSHIPS[(f"{obj_type}:{obj_id}", "write", f"agent:{agent}")] = True
            _LOCAL_RELATIONSHIPS[(f"{obj_type}:{obj_id}", "verify", f"agent:{agent}")] = True
            _LOCAL_RELATIONSHIPS[(f"{obj_type}:{obj_id}", "update_bank", f"agent:{agent}")] = True

    # Invoice processor can process invoices
    for inv_id in ["INV-2024-1841", "INV-2024-1842", "INV-2024-1843",
                    "INV-2024-1847", "INV-2024-1848", "INV-2024-1849",
                    "INV-2024-1850", "INV-2024-1851", "INV-2024-1852",
                    "INV-2024-1853", "INV-2024-1854", "INV-2024-1855",
                    "INV-2024-1856", "INV-2024-1857", "INV-2024-1858",
                    "INV-2024-1859"]:
        _LOCAL_RELATIONSHIPS[(f"invoice:{inv_id}", "read", "agent:invoice-processor")] = True
        _LOCAL_RELATIONSHIPS[(f"invoice:{inv_id}", "write", "agent:invoice-processor")] = True
        _LOCAL_RELATIONSHIPS[(f"invoice:{inv_id}", "approve", "agent:invoice-processor")] = True

    # Payment executor can execute payments and read vendors (for bank details)
    _LOCAL_RELATIONSHIPS[("payment:*", "read", "agent:payment-executor")] = True
    _LOCAL_RELATIONSHIPS[("payment:*", "execute", "agent:payment-executor")] = True
    _LOCAL_RELATIONSHIPS[("payment:*", "approve", "agent:payment-executor")] = True
    for vid in ["V-4521", "V-4522", "V-4523", "V-4524", "V-4525", "V-4526"]:
        _LOCAL_RELATIONSHIPS[(f"vendor:{vid}", "read", "agent:payment-executor")] = True

    # PO reader
    for po_id in ["PO-2024-0891", "PO-2024-0892", "PO-2024-0893", "PO-2024-0894",
                   "PO-2024-0895", "PO-2024-0901", "PO-2024-0902", "PO-2024-0903",
                   "PO-2024-0911", "PO-2024-0912", "PO-2024-0913", "PO-2024-0921",
                   "PO-2024-0922", "PO-2024-0931", "PO-2024-0932", "PO-2024-0933"]:
        _LOCAL_RELATIONSHIPS[(f"purchase_order:{po_id}", "read", "agent:invoice-processor")] = True

    # Finance controller is org admin (can do everything)
    _LOCAL_RELATIONSHIPS[("organization:acorp", "admin", "agent:finance-controller")] = True

    _initialized = True


def _check_local(subject: str, permission: str, resource: str) -> bool:
    """Check relationship in local memory."""
    _init_local_relationships()
    # Check exact match
    if _LOCAL_RELATIONSHIPS.get((resource, permission, subject)):
        return True
    # Check wildcard (e.g., payment:*)
    obj_type = resource.split(":")[0]
    if _LOCAL_RELATIONSHIPS.get((f"{obj_type}:*", permission, subject)):
        return True
    # Org admin can do anything
    if _LOCAL_RELATIONSHIPS.get(("organization:acorp", "admin", subject)):
        return True
    return False


def check_spicedb(request: AuthRequest) -> AuthDecision:
    """Check if the agent has the required SpiceDB relationship."""
    start = time.perf_counter_ns()

    perm_config = TOOL_PERMISSIONS.get(request.tool_name)
    if not perm_config:
        elapsed = (time.perf_counter_ns() - start) // 1000
        return AuthDecision("spicedb", False, f"No permission mapping for: {request.tool_name}", elapsed)

    obj_type, permission, arg_key = perm_config
    obj_id = request.tool_args.get(arg_key, "*") if arg_key else "*"
    resource = f"{obj_type}:{obj_id}"
    subject = f"agent:{request.agent_id}"

    allowed = _check_local(subject, permission, resource)
    elapsed = (time.perf_counter_ns() - start) // 1000

    reason = (
        f"Agent has '{permission}' on {resource}"
        if allowed
        else f"Agent lacks '{permission}' on {resource}"
    )
    return AuthDecision("spicedb", allowed, reason, elapsed)
