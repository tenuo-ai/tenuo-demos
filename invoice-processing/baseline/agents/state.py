"""Shared state definitions for the AP automation agent graph."""

import operator
from typing import Annotated, Any, TypedDict


class APState(TypedDict):
    """Top-level state for the AP automation graph.

    Design notes:
    - `warrant` is stored as base64 string (checkpoint-safe, never a BoundWarrant)
    - `key_id` is NOT in state — passed via config["configurable"]["tenuo_key_id"]
    - `events` accumulates SSE events for the dashboard
    """

    messages: Annotated[list, operator.add]
    warrant: str  # Base64-encoded warrant token
    invoice_batch: list[str]  # Invoice IDs to process
    current_invoice: str | None
    processing_results: dict[str, Any]  # invoice_id -> result
    attack_mode: str | None  # None, "prompt", "injection", "simulate"
    auth_stack: str  # "standard" or "tenuo"
    events: Annotated[list[dict], operator.add]


class InvoiceProcessorState(TypedDict):
    """State for the Level 2 Invoice Processor subgraph."""

    messages: Annotated[list, operator.add]
    warrant: str
    invoice_id: str
    vendor_id: str | None
    po_id: str | None
    amount: float | None
    department: str | None
    attack_mode: str | None  # Passed from parent for prompt swapping (Mode 1)
    result: dict[str, Any] | None
    events: Annotated[list[dict], operator.add]


class PaymentExecutorState(TypedDict):
    """State for the Level 2 Payment Executor subgraph."""

    messages: Annotated[list, operator.add]
    warrant: str
    invoice_id: str
    vendor_id: str
    amount: float
    currency: str
    result: dict[str, Any] | None
    events: Annotated[list[dict], operator.add]


class VendorVerificationState(TypedDict):
    """State for the Level 3 Vendor Verification subgraph."""

    messages: Annotated[list, operator.add]
    warrant: str
    vendor_id: str
    result: dict[str, Any] | None
    events: Annotated[list[dict], operator.add]


class FXRateState(TypedDict):
    """State for the Level 3 FX Rate Checker subgraph."""

    messages: Annotated[list, operator.add]
    warrant: str
    from_currency: str
    to_currency: str
    rate: float | None
    events: Annotated[list[dict], operator.add]
