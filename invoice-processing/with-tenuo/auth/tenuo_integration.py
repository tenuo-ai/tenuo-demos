"""Tenuo Cloud integration for Act 3.

Uses TenuoToolNode as a drop-in replacement for ToolNode. The warrant
from Tenuo Cloud flows through LangGraph state. TenuoToolNode reads it,
checks constraints, and blocks unauthorized calls.

Required environment variables:
  TENUO_CONTROL_PLANE_URL  — base URL, no /v1 (e.g. https://api-staging.tenuo.ai)
  TENUO_API_KEY            — API key for the control plane
  TENUO_SIGNING_KEY        — base64 Ed25519 private key. ONE key used for:
                               • POST /v1/agents/claim   (agent identity)
                               • POST /v1/authorizers/register
                               • Receipt signing (non-repudiable authz events)
                               • TenuoToolNode PoP signing (via KeyRegistry)
                             Generate:
                               python -c "from tenuo.keys import SigningKey; import base64;
                               print(base64.b64encode(SigningKey.generate().secret_key_bytes()).decode())"

  TENUO_KEY_<AGENT_ID>     — same value as TENUO_SIGNING_KEY, named for
                             load_tenuo_keys() to auto-register in Python KeyRegistry.
                             e.g. TENUO_KEY_DEMO_FINANCE=<same base64 value>

Optional:
  TENUO_AGENT_ID           — agent name to register under (default: demo-finance)

NOTE: Do NOT set TENUO_CONNECT_TOKEN. The connect token path auto-generates
an ephemeral key and ignores TENUO_SIGNING_KEY, breaking PoP signing.
"""

import base64
import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def _load_signing_key():
    """Load the Ed25519 signing key from TENUO_SIGNING_KEY (or TENUO_KEY_DEMO_FINANCE).

    Returns a tenuo_core.SigningKey instance, or None if not set.
    """
    raw = os.environ.get("TENUO_SIGNING_KEY") or os.environ.get("TENUO_KEY_DEMO_FINANCE", "")
    if not raw:
        return None
    try:
        from tenuo_core import SigningKey
        return SigningKey.from_bytes(base64.b64decode(raw))
    except Exception as e:
        logger.warning("Could not load signing key: %s", e)
        return None


def setup_tenuo():
    """Connect to Tenuo Cloud and register signing keys. Call once at startup.

    Uses the legacy env-var path (TENUO_CONTROL_PLANE_URL + TENUO_API_KEY +
    TENUO_SIGNING_KEY) rather than a connect token. This ensures Tenuo Cloud
    registers OUR known key as the agent identity — connect tokens auto-generate
    an ephemeral key and ignore TENUO_SIGNING_KEY entirely.
    """
    global _initialized
    if _initialized:
        return

    api_key = os.environ.get("TENUO_API_KEY")
    control_url = os.environ.get("TENUO_CONTROL_PLANE_URL")

    if not (api_key and control_url):
        raise RuntimeError(
            "Cloud mode requires TENUO_CONTROL_PLANE_URL + TENUO_API_KEY + "
            "TENUO_SIGNING_KEY. Set TENUO_MODE=local to run without Tenuo Cloud."
        )

    signing_key = _load_signing_key()
    if signing_key is None:
        logger.warning(
            "TENUO_SIGNING_KEY not set — SDK will generate a random key. "
            "The warrant holder will not match; PoP signing will fail."
        )
    else:
        logger.info("Signing key loaded. Public key: %s", signing_key.public_key_bytes().hex())

    # authorizer_name must match the agent ID configured in Tenuo Cloud so that
    # POST /v1/agents/claim registers our key under the correct agent identity.
    agent_id = os.environ.get("TENUO_AGENT_ID", "demo-finance")

    try:
        from tenuo.control_plane import connect
        connect(authorizer_name=agent_id, signing_key=signing_key)
        logger.info("Tenuo Cloud connected — agent '%s' claimed", agent_id)
    except Exception as e:
        raise RuntimeError(f"Tenuo Cloud connection failed: {e}") from e

    # Register key in Python's KeyRegistry so TenuoToolNode can sign PoP proofs.
    from tenuo.langgraph import load_tenuo_keys
    n = load_tenuo_keys()
    if n == 0:
        logger.warning("No TENUO_KEY_* env vars found — TenuoToolNode PoP signing will fail.")
    else:
        logger.info("Loaded %d signing key(s) into KeyRegistry", n)

    # Configure trusted root(s) so TenuoToolNode can verify warrant signatures.
    # TENUO_TRUSTED_ROOT is the issuer public key (hex) of the Tenuo Cloud trigger.
    # Without this, enforce_tool_call rejects all warrants as self-signed (fail-closed).
    # Trusted roots: Tenuo Cloud root key + our own signing key.
    # The cloud key validates root warrants from the trigger.
    # Our own key validates attenuated sub-warrants we sign during delegation.
    trusted_roots = []
    trusted_root_raw = os.environ.get("TENUO_TRUSTED_ROOT", "")
    if trusted_root_raw:
        try:
            from tenuo_core import PublicKey
            key_bytes = base64.b64decode(trusted_root_raw)
            trusted_roots.append(PublicKey.from_bytes(key_bytes))
            logger.info("Trusted root (Tenuo Cloud): %s...", key_bytes.hex()[:16])
        except Exception as e:
            logger.warning("Could not load TENUO_TRUSTED_ROOT: %s", e)
    else:
        logger.warning("TENUO_TRUSTED_ROOT not set — root warrant verification will fail.")

    if signing_key is not None:
        trusted_roots.append(signing_key.public_key)
        logger.info("Trusted root (self, for delegation): %s...", signing_key.public_key_bytes().hex()[:16])

    if trusted_roots:
        import tenuo as _tenuo
        _tenuo.configure(trusted_roots=trusted_roots)

    _initialized = True


async def attenuate_for_invoice_processor_cloud(root_warrant_b64: str) -> str:
    """Attenuate the cloud root warrant for the Invoice Processor.

    Removes update_vendor_bank so a prompt-injected agent cannot redirect
    payments. Signed by our own key; holder stays the same (demo-finance).
    """
    setup_tenuo()
    from tenuo_core import Warrant
    root = Warrant.from_base64(root_warrant_b64)
    sk = _load_signing_key()
    if sk is None:
        raise RuntimeError("TENUO_SIGNING_KEY not set — cannot attenuate warrant")
    child = root.attenuate(
        {
            "read_invoice": {},
            "read_po": {},
            "lookup_vendor": {},
            "verify_vendor": {},
            "approve_invoice": {},
            # NO update_vendor_bank — this is the key protection
        },
        signing_key=sk,
        holder=sk.public_key,
        ttl_seconds=600,
    )
    logger.info("Attenuated cloud warrant for invoice-processor (5 tools, NO update_vendor_bank)")
    return child.to_base64()


async def attenuate_for_payment_executor_cloud(root_warrant_b64: str, vendor_id: str) -> str:
    """Attenuate the cloud root warrant for the Payment Executor.

    Pins bank_account and bank_routing from the LIVE vendor master at
    delegation time — before any injection can poison the DB.
    """
    setup_tenuo()
    from tenuo_core import Warrant, Exact, Wildcard
    root = Warrant.from_base64(root_warrant_b64)
    sk = _load_signing_key()
    if sk is None:
        raise RuntimeError("TENUO_SIGNING_KEY not set — cannot attenuate warrant")

    from tools.db import get_pool
    pool = await get_pool()
    vendor = await pool.fetchrow(
        "SELECT bank_account, bank_routing FROM vendors WHERE id = $1", vendor_id
    )
    if not vendor:
        raise ValueError(f"Vendor {vendor_id} not found")

    child = root.attenuate(
        {
            "lookup_vendor": {},
            "initiate_payment": {
                "bank_account": Exact(vendor["bank_account"]),
                "bank_routing": Exact(vendor["bank_routing"]),
                "vendor_id": Exact(vendor_id),
                "invoice_id": Wildcard(),
                "amount": Wildcard(),
            },
            "approve_payment": {},
            "get_fx_rate": {},
        },
        signing_key=sk,
        holder=sk.public_key,
        ttl_seconds=300,
    )
    logger.info(
        "Attenuated cloud warrant for payment-executor "
        "(bank_account=%s pinned from vendor master)", vendor["bank_account"]
    )
    return child.to_base64()


def build_tenuo_tool_node(tools):
    """Create a TenuoToolNode for the given tools.

    Drop-in replacement for ToolNode(tools). The warrant in LangGraph
    state is decoded and constraints are checked automatically.
    """
    setup_tenuo()

    cp = None
    try:
        from tenuo.control_plane import get_client
        cp = get_client()
    except Exception as e:
        logger.warning("Could not get Tenuo Cloud control plane client (non-fatal): %s", e)

    agent_id = os.environ.get("TENUO_AGENT_ID", "demo-finance")
    from tenuo.langgraph import TenuoToolNode
    return TenuoToolNode(tools, key_id=agent_id, control_plane=cp)
