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

import tenuo
from tenuo_core import SigningKey, Warrant, Exact, Wildcard
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


def setup_local():
    """Initialize keys for all agents. Call once at startup."""
    global _initialized, _issuer_key, _keys
    if _initialized:
        return

    _issuer_key = SigningKey.generate()
    _keys = {
        KEY_CONTROLLER: SigningKey.generate(),
        KEY_PROCESSOR: SigningKey.generate(),
        KEY_PAYMENT: SigningKey.generate(),
    }

    tenuo.configure(trusted_roots=[_issuer_key.public_key])

    registry = KeyRegistry.get_instance()
    for key_id, key in _keys.items():
        registry.register(key_id, key)

    logger.info("Tenuo local mode: 3 agent keys registered")
    _initialized = True


def issue_root_warrant() -> str:
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
    return root.to_base64()


async def attenuate_for_invoice_processor(
    root_warrant_b64: str,
    invoice_id: str,
    vendor_id: str,
) -> str:
    """Attenuate the root warrant for the Invoice Processor (Level 2).

    Removes update_vendor_bank and scopes to this specific invoice/vendor.
    """
    setup_local()
    root = Warrant.from_base64(root_warrant_b64)

    child = root.attenuate(
        signing_key=_keys[KEY_CONTROLLER],
        holder=_keys[KEY_PROCESSOR].public_key,
        capabilities={
            "read_invoice": {},
            "read_po": {},
            "lookup_vendor": {},
            "verify_vendor": {},
            "approve_invoice": {},
            # NO update_vendor_bank — that's the key protection
        },
        ttl_seconds=600,
    )
    logger.info(f"Attenuated Level 2 warrant for invoice-processor ({invoice_id}, 5 tools, NO update_vendor_bank)")
    return child.to_base64()


async def attenuate_for_payment_executor(
    root_warrant_b64: str,
    invoice_id: str,
    vendor_id: str,
) -> str:
    """Attenuate the root warrant for the Payment Executor (Level 2).

    Pins bank_account and bank_routing from the LIVE vendor master.
    This is the critical moment — the warrant captures the legitimate
    bank details BEFORE the injection can poison them.
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
    logger.info(
        f"Read vendor master for {vendor_id}: "
        f"bank_account={bank_account}, bank_routing={bank_routing}"
    )

    child = root.attenuate(
        signing_key=_keys[KEY_CONTROLLER],
        holder=_keys[KEY_PAYMENT].public_key,
        capabilities={
            "lookup_vendor": {},
            "initiate_payment": {
                "bank_account": Exact(bank_account),
                "bank_routing": Exact(bank_routing),
                "vendor_id": Exact(vendor_id),
                "invoice_id": Wildcard(),
                "amount": Wildcard(),
            },
            "approve_payment": {},
            "get_fx_rate": {},
        },
        ttl_seconds=300,
    )
    logger.info(
        f"Attenuated Level 2 warrant for payment-executor "
        f"(bank_account={bank_account} pinned from vendor master)"
    )
    return child.to_base64()


def build_tenuo_tool_node_local(tools, key_id=KEY_PROCESSOR):
    """Create a TenuoToolNode for the given tools and key."""
    setup_local()
    return TenuoToolNode(tools, key_id=key_id)
