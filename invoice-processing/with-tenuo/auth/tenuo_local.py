"""Tenuo local mode — self-serve demo without Tenuo Cloud.

Issues warrants locally using Warrant.issue() with the SDK's built-in
cryptographic operations. No network calls, no cloud dependencies.

The warrant constrains the AP pipeline:
  - 11 tools granted (everything EXCEPT update_vendor_bank)
  - initiate_payment is tightly constrained to the legitimate vendor's
    bank account, routing number, and vendor ID
  - All other tools get Wildcard() on all parameters (unconstrained)

Key demo moment: the injection tries to redirect payment to attacker
bank account 8847291034, but the warrant locks bank_account to
7291034851. Tenuo blocks the call.
"""

import logging

from tenuo_core import SigningKey, Warrant, Exact, Wildcard
from tenuo.keys import KeyRegistry
from tenuo.langgraph import TenuoToolNode
import tenuo

logger = logging.getLogger(__name__)

_KEY_ID = "demo-finance-controller"
_initialized = False

# Module-level keys (generated once at startup)
_issuer_key: SigningKey | None = None
_agent_key: SigningKey | None = None


def setup_local():
    """Initialize Tenuo SDK for local mode. Call once at startup."""
    global _initialized, _issuer_key, _agent_key
    if _initialized:
        return

    # Generate fresh keypairs for the demo
    _issuer_key = SigningKey.generate()
    _agent_key = SigningKey.generate()

    # Configure trusted roots so warrant chain verification passes
    tenuo.configure(trusted_roots=[_issuer_key.public_key])
    logger.info("Tenuo local mode: configured with local issuer key")

    # Register the agent's signing key in the KeyRegistry
    registry = KeyRegistry.get_instance()
    registry.register(_KEY_ID, _agent_key)
    logger.info(f"Tenuo local mode: agent key registered as '{_KEY_ID}'")

    _initialized = True


def issue_local_warrant() -> str:
    """Issue a warrant for the AP automation pipeline.

    Returns the warrant as a base64-encoded string suitable for
    LangGraph state transport.

    Capabilities:
      - read_invoice:      Wildcard (unconstrained)
      - read_po:           Wildcard (unconstrained)
      - list_invoices:     Wildcard (unconstrained)
      - approve_invoice:   Wildcard (unconstrained)
      - lookup_vendor:     Wildcard (unconstrained)
      - verify_vendor:     Wildcard (unconstrained)
      - initiate_payment:  bank_account=Exact("7291034851"),
                           bank_routing=Exact("021000021"),
                           vendor_id=Exact("V-4521"),
                           invoice_id=Wildcard(),
                           amount=Wildcard()
      - approve_payment:   Wildcard (unconstrained)
      - get_fx_rate:       Wildcard (unconstrained)
      - flag_expense:      Wildcard (unconstrained)
      - approve_expense:   Wildcard (unconstrained)

    NOT included: update_vendor_bank (the attack target)
    """
    setup_local()

    capabilities = {
        # Invoice tools — unconstrained
        "read_invoice": {},
        "read_po": {},
        "list_invoices": {},
        "approve_invoice": {},
        # Vendor tools — unconstrained (but update_vendor_bank is EXCLUDED)
        "lookup_vendor": {},
        "verify_vendor": {},
        # Payment tools — initiate_payment is tightly constrained
        "initiate_payment": {
            "bank_account": Exact("7291034851"),
            "bank_routing": Exact("021000021"),
            "vendor_id": Exact("V-4521"),
            "invoice_id": Wildcard(),
            "amount": Wildcard(),
        },
        "approve_payment": {},
        "get_fx_rate": {},
        # Review tools — unconstrained
        "flag_expense": {},
        "approve_expense": {},
    }

    warrant = Warrant.issue(
        keypair=_issuer_key,
        capabilities=capabilities,
        ttl_seconds=1800,
        holder=_agent_key.public_key,
    )

    warrant_b64 = warrant.to_base64()
    logger.info(
        f"Tenuo local mode: issued warrant with {len(capabilities)} capabilities "
        f"(ttl=1800s, holder={_KEY_ID})"
    )
    return warrant_b64


def build_tenuo_tool_node_local(tools):
    """Create a TenuoToolNode using the local key setup.

    Drop-in replacement for build_tenuo_tool_node() that works without
    Tenuo Cloud. The agent key is already registered in KeyRegistry
    by setup_local().
    """
    setup_local()

    return TenuoToolNode(
        tools,
        key_id=_KEY_ID,
    )
