"""Tenuo local mode — self-serve demo without Tenuo Cloud.

Issues warrants locally using the SDK. Supports 3-level delegation:

  Level 1: Root warrant (Finance Controller) — all tools, all vendors
  Level 2: Attenuated per-invoice (Invoice Processor, Payment Executor)
  Level 3: Further attenuated (Vendor Verification — read-only)

Bank account constraints are derived from the LIVE vendor master at
delegation time — not hardcoded. The warrant captures a point-in-time
snapshot of what the world looks like BEFORE the injection poisons the DB.
"""

import logging

import json
import os

import tenuo
from tenuo_core import SigningKey, Warrant, Exact, Range, OneOf
from tenuo.keys import KeyRegistry
from tenuo.langgraph import TenuoToolNode

logger = logging.getLogger(__name__)

# Key IDs for each agent level
KEY_CONTROLLER = "finance-controller"
KEY_PROCESSOR = "invoice-processor"
KEY_PAYMENT = "payment-executor"

_initialized = False
_issuer_key: SigningKey | None = None
_keys: dict[str, SigningKey] = {}


def setup_local(force: bool = False):
    """Initialize keys for all agents. Call once at startup."""
    global _initialized, _issuer_key, _keys
    if _initialized and not force:
        return

    # Use registered agent key from env if available (cloud mode),
    # otherwise generate fresh keys (local mode)
    agent_key_hex = os.environ.get("TENUO_AGENT_KEY")
    if agent_key_hex:
        # Cloud mode — use the registered key for the controller
        controller_key = SigningKey.from_bytes(bytes.fromhex(agent_key_hex))
        _issuer_key = controller_key  # In cloud mode, cloud is the issuer
    else:
        controller_key = SigningKey.generate()
        _issuer_key = SigningKey.generate()

    _keys = {
        KEY_CONTROLLER: controller_key,
        KEY_PROCESSOR: SigningKey.generate(),
        KEY_PAYMENT: SigningKey.generate(),
    }

    # Trust roots: local issuer + controller (for attenuated warrants)
    trusted = [_keys[KEY_CONTROLLER].public_key]
    if _issuer_key != controller_key:
        trusted.append(_issuer_key.public_key)

    # In cloud mode, also trust the cloud root key
    root_key_b64 = os.environ.get("TENUO_ROOT_PUBLIC_KEY")
    if root_key_b64:
        import base64
        from tenuo_core import PublicKey
        trusted.append(PublicKey.from_bytes(base64.b64decode(root_key_b64)))

    tenuo.configure(trusted_roots=trusted)

    registry = KeyRegistry.get_instance()
    for key_id, key in _keys.items():
        registry.register(key_id, key)

    logger.info("Tenuo local mode: 3 agent keys registered")
    _initialized = True


async def issue_root_warrant() -> str:
    """Issue the Level 1 root warrant for the Finance Controller.

    This warrant has ALL tools and NO constraints — the controller
    attenuates it per-invoice when delegating to specialists.
    """
    setup_local()

    root = Warrant.issue(
        keypair=_issuer_key,
        capabilities={
            "read_invoice": {},
            "read_po": {},
            "list_invoices": {},
            "approve_invoice": {},
            "lookup_vendor": {},
            "verify_vendor": {},
            "update_vendor_bank": {},
            "initiate_payment": {},
            "approve_payment": {},
            "get_fx_rate": {},
            "flag_expense": {},
            "approve_expense": {},
        },
        ttl_seconds=1800,
        holder=_keys[KEY_CONTROLLER].public_key,
    )
    logger.info("Issued Level 1 root warrant (12 tools, unconstrained)")
    await _log_warrant("finance-controller", "root", root, {
        "level": 1,
        "tools": sorted(root.tools),
        "constraints": "unconstrained",
        "ttl_seconds": 1800,
    })
    return root.to_base64()


async def attenuate_for_invoice_processor(
    root_warrant_b64: str,
    invoice_id: str,
    vendor_id: str,
) -> str:
    """Attenuate the root warrant for the Invoice Processor (Level 2).

    Removes update_vendor_bank entirely (tool-level restriction).
    All other tools are unconstrained — the key protection is tool exclusion.
    10-minute TTL (temporal binding).
    """
    setup_local()
    root = Warrant.from_base64(root_warrant_b64)

    child = root.attenuate(
        {
            "read_invoice": {},       # Unconstrained — open mode
            "read_po": {},
            "lookup_vendor": {},
            "verify_vendor": {},
            "approve_invoice": {},
            # NO update_vendor_bank — tool-level restriction
        },
        signing_key=_keys[KEY_CONTROLLER],
        holder=_keys[KEY_PROCESSOR].public_key,
        ttl_seconds=600,
    )
    logger.info(f"Attenuated L2 warrant: invoice-processor (5 tools, NO update_vendor_bank, TTL=10m)")
    await _log_warrant("invoice-processor", "attenuated", child, {
        "level": 2,
        "parent": "finance-controller",
        "tools": sorted(child.tools),
        "removed": ["update_vendor_bank"],
        "constraints": "unconstrained (tool-level restriction only)",
        "ttl_seconds": 600,
        "invoice_id": invoice_id,
        "vendor_id": vendor_id,
    })
    return child.to_base64()


async def attenuate_for_payment_executor(
    root_warrant_b64: str,
    invoice_id: str,
    vendor_id: str,
) -> str:
    """Attenuate the root warrant for the Payment Executor (Level 2).

    Pins bank_account and bank_routing from the LIVE vendor master (Exact).
    5-minute TTL. The warrant is a cryptographic snapshot of the legitimate
    bank details captured BEFORE the injection can poison them.
    """
    setup_local()
    root = Warrant.from_base64(root_warrant_b64)

    # Read the vendor's CURRENT bank details from the database
    from tools.db import get_pool
    pool = await get_pool()
    vendor = await pool.fetchrow(
        "SELECT bank_account, bank_routing FROM vendors WHERE id = $1",
        vendor_id,
    )

    if not vendor:
        raise ValueError(f"Vendor {vendor_id} not found")

    bank_account = vendor["bank_account"]
    bank_routing = vendor["bank_routing"]

    logger.info(f"Read vendor master for {vendor_id}: bank={bank_account}")

    # Read invoice amount for the Range constraint
    inv = await pool.fetchrow("SELECT amount FROM invoices WHERE id = $1", invoice_id)
    amount_limit = float(inv["amount"]) if inv else 50000.0

    child = root.attenuate(
        {
            "lookup_vendor": {},
            "initiate_payment": {
                "bank_account": Exact(bank_account),         # Pinned from vendor master
                "bank_routing": Exact(bank_routing),         # Pinned from vendor master
                "vendor_id": Exact(vendor_id),               # Locked to this vendor
                "invoice_id": OneOf([invoice_id]),            # Only this invoice
                "amount": Range(min=0.0, max=amount_limit),  # Capped at invoice amount
            },
            "approve_payment": {},
            "get_fx_rate": {},
        },
        signing_key=_keys[KEY_CONTROLLER],
        holder=_keys[KEY_PAYMENT].public_key,
        ttl_seconds=300,
    )
    logger.info(f"Attenuated L2 warrant: payment-executor (bank={bank_account} pinned)")
    await _log_warrant("payment-executor", "attenuated", child, {
        "level": 2,
        "parent": "finance-controller",
        "tools": sorted(child.tools),
        "constraints": {
            "initiate_payment": {
                "bank_account": f"Exact({bank_account})",
                "bank_routing": f"Exact({bank_routing})",
                "vendor_id": f"Exact({vendor_id})",
                "invoice_id": f"OneOf([{invoice_id}])",
                "amount": f"Range(0, {amount_limit})",
            },
        },
        "ttl_seconds": 300,
        "invoice_id": invoice_id,
        "vendor_id": vendor_id,
    })
    return child.to_base64()


async def _log_warrant(agent_id: str, warrant_type: str, warrant: Warrant, details: dict):
    """Log warrant issuance/attenuation to the agent_logs table."""
    try:
        from agents.logger import log_event
        await log_event(
            agent_id=agent_id,
            event_type="warrant",
            content=json.dumps(details, indent=2),
            metadata={"warrant_type": warrant_type, "tools": sorted(warrant.tools)},
        )
    except Exception:
        pass  # Non-fatal


def build_tenuo_tool_node_local(tools, key_id=KEY_PROCESSOR):
    """Create a TenuoToolNode for the given tools and key."""
    setup_local()
    return TenuoToolNode(tools, key_id=key_id)
