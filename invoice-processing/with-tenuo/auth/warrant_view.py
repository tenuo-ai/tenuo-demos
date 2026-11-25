"""Decode minted warrants for the dashboard's warrant inspector.

Every warrant the Finance Controller mints (the root, and the per-invoice
children it attenuates for the Invoice Processor and Payment Executor) is
recorded on the run as a ``warrant_minted`` event, with its decoded fields.
This is display only: enforcement still verifies the warrant itself.
"""

from typing import Any

from tenuo_core import Warrant

from agents.logger import log_event


def _key_hex(key: Any) -> str | None:
    if key is None:
        return None
    try:
        return key.to_bytes().hex()
    except Exception:
        return str(key)


def _field(w: Warrant, name: str) -> Any:
    # Some fields are exposed as methods, others as attributes.
    value = getattr(w, name)
    return value() if callable(value) else value


def describe_warrant(warrant_b64: str) -> dict[str, Any]:
    """Decoded fields of a warrant, as shown in the dashboard."""
    w = Warrant.from_base64(warrant_b64)
    return {
        "id": _field(w, "id"),
        "type": str(_field(w, "warrant_type")),
        "depth": _field(w, "depth"),
        "max_depth": _field(w, "max_depth"),
        "issuer": _key_hex(_field(w, "issuer")),
        "holder": _key_hex(_field(w, "authorized_holder")),
        "parent_hash": _field(w, "parent_hash"),
        "expires_at": str(_field(w, "expires_at")),
        "ttl_seconds": _field(w, "ttl_seconds"),
        "tools": {
            tool: {arg: repr(constraint) for arg, constraint in constraints.items()}
            for tool, constraints in _field(w, "capabilities").items()
        },
        "token": warrant_b64,
    }


async def log_warrant_minted(
    holder_agent: str, warrant_b64: str, invoice_id: str | None = None
) -> None:
    """Record a minted warrant on the current run. Never raises."""
    try:
        decoded = describe_warrant(warrant_b64)
    except Exception as e:  # display only: a decode failure must not stop the run
        decoded = {"error": f"could not decode warrant: {type(e).__name__}"}
    await log_event(
        "finance-controller",
        "warrant_minted",
        content=f"Minted warrant for {holder_agent}",
        metadata={"holder_agent": holder_agent, "invoice_id": invoice_id, "warrant": decoded},
    )
