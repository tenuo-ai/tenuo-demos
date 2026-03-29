"""Tenuo Cloud integration for Act 3.

Uses TenuoToolNode as a drop-in replacement for ToolNode. The warrant
from Tenuo Cloud flows through LangGraph state. TenuoToolNode reads it,
checks constraints, and blocks unauthorized calls.

Required environment variables:
  TENUO_AGENT_KEY          — hex-encoded Ed25519 private key for PoP signatures
  TENUO_ROOT_PUBLIC_KEY    — base64-encoded root public key from Tenuo Cloud dashboard
  TENUO_API_KEY            — API key for control plane receipt streaming (optional)
  TENUO_CONTROL_PLANE_URL  — Control plane URL (optional)
"""

import base64
import logging
import os

import tenuo
from tenuo_core import PublicKey, SigningKey
from tenuo.keys import KeyRegistry
from tenuo.langgraph import TenuoToolNode

logger = logging.getLogger(__name__)

_KEY_ID = "demo-finance-controller"
_initialized = False


def setup_tenuo():
    """Initialize Tenuo SDK for Cloud mode. Call once at startup."""
    global _initialized
    if _initialized:
        return

    agent_key_hex = os.environ.get("TENUO_AGENT_KEY")
    root_key_b64 = os.environ.get("TENUO_ROOT_PUBLIC_KEY")

    if not agent_key_hex or not root_key_b64:
        raise RuntimeError(
            "Cloud mode requires TENUO_AGENT_KEY and TENUO_ROOT_PUBLIC_KEY. "
            "Set TENUO_MODE=local to run without Tenuo Cloud."
        )

    # Configure trusted roots so warrant signatures are verified
    root_key = PublicKey.from_bytes(base64.b64decode(root_key_b64))
    tenuo.configure(trusted_roots=[root_key])

    # Register the agent's signing key for PoP
    key = SigningKey.from_bytes(bytes.fromhex(agent_key_hex))
    KeyRegistry.get_instance().register(_KEY_ID, key)
    logger.info("Tenuo Cloud mode initialized")

    # Stream receipts to Tenuo Cloud via the SDK.
    # The authorizer sidecar also streams its own events (heartbeat, SRL sync).
    api_key = os.environ.get("TENUO_API_KEY")
    control_url = os.environ.get("TENUO_CONTROL_PLANE_URL")
    if api_key and control_url:
        try:
            from tenuo.control_plane import connect
            connect(url=control_url + "/api", api_key=api_key, authorizer_name="demo-ap-sdk")
            logger.info("SDK connected to Tenuo Cloud for receipt streaming")
        except Exception as e:
            logger.warning(f"SDK cloud connection failed (non-fatal): {e}")

    _initialized = True


def build_tenuo_tool_node(tools):
    """Create a TenuoToolNode for the given tools.

    Drop-in replacement for ToolNode(tools). The warrant in LangGraph
    state is decoded and constraints are checked automatically.
    """
    setup_tenuo()

    # If the SDK is connected to the control plane (uncomment above),
    # pass the client here for receipt streaming.
    cp = None
    try:
        from tenuo.control_plane import get_client
        cp = get_client()
    except Exception:
        pass

    return TenuoToolNode(tools, key_id=_KEY_ID, control_plane=cp)
