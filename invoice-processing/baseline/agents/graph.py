"""Main LangGraph StateGraph for the AP Automation demo.

This is the top-level graph that orchestrates the multi-agent pipeline:
  Level 1: Finance Controller (orchestrator)
  Level 2: Invoice Processor, Payment Executor, Expense Reviewer
  Level 3: Vendor Verification, FX Rate Checker (spawned by Level 2)

The graph processes invoices one at a time from the batch, routing each
through the appropriate specialist subgraphs.
"""

import json
import os

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from agents.events import agent_status_event, delegation_event
from agents.finance_controller import finance_controller_node
from agents.logger import log_delegation, log_status, new_run
from agents.invoice_processor import build_invoice_processor_graph
from agents.payment_executor import build_payment_executor_graph
from agents.state import APState, InvoiceProcessorState, PaymentExecutorState
from server.events import publish

VENDOR_PORTAL_URL = os.getenv("VENDOR_PORTAL_URL", "http://localhost:8082")


async def _fetch_invoice_from_portal(invoice_id: str, attack_mode: str | None = None) -> dict:
    """Fetch invoice from vendor portal (where injection payloads live).

    Raises RuntimeError if the portal is unreachable in injection mode so the
    demo fails loudly rather than silently returning the clean DB invoice.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{VENDOR_PORTAL_URL}/api/invoices/{invoice_id}")
            return resp.json()
        except httpx.ConnectError:
            if attack_mode == "injection":
                raise RuntimeError(
                    "Vendor portal is unreachable — injection payloads cannot be served. "
                    "Start it with: uvicorn vendor_portal.server:app --port 8082"
                )
            # Act 1 (no attack): falling back to DB is fine
            from tools.invoice_tools import read_invoice
            data = await read_invoice.ainvoke({"invoice_id": invoice_id})
            return json.loads(data)


async def process_invoice_node(state: APState) -> dict:
    """Invoke the Invoice Processor subgraph for the current invoice.

    This is the Level 1 → Level 2 delegation point. Fetches the invoice
    from the vendor portal (where injection payloads are served in Act 2).
    """
    invoice_id = state["current_invoice"]
    if not invoice_id:
        return {"messages": [], "events": []}


    # Fetch invoice from vendor portal (injection payloads served here)
    invoice = await _fetch_invoice_from_portal(invoice_id, attack_mode=state.get("attack_mode"))

    # Log delegation
    delegate_tools = ["read_invoice", "read_po", "lookup_vendor",
                      "verify_vendor", "update_vendor_bank", "approve_invoice"]
    await log_status("finance-controller", f"Processing invoice {invoice_id}")
    await log_delegation("finance-controller", "invoice-processor", delegate_tools,
                         invoice_id=invoice_id, amount=invoice.get("amount"))

    events = [
        agent_status_event("finance-controller", "delegating",
                           invoice_id=invoice_id, to="invoice-processor"),
        delegation_event("finance-controller", "invoice-processor",
                         tools=delegate_tools, ttl_minutes=10),
    ]
    for e in events:
        await publish(e)
    processor = build_invoice_processor_graph().compile()

    # Build the initial message with invoice data (this is where injection arrives)
    # The invoice data is pre-fetched from the vendor portal so the agent
    # doesn't need to call read_invoice again (which would hit the DB and miss
    # the vendor notes including any remittance update notices).
    invoice_context = json.dumps(invoice, indent=2)
    task_message = (
        f"Process invoice {invoice_id}. The invoice data has already been "
        f"retrieved from the vendor portal:\n\n{invoice_context}\n\n"
        f"Now continue with the remaining SOP steps: verify the PO, look up "
        f"the vendor, process any bank change notices in the notes field, "
        f"and approve the invoice."
    )

    sub_state: InvoiceProcessorState = {
        "messages": [HumanMessage(content=task_message)],
        "warrant": state.get("warrant", ""),
        "invoice_id": invoice_id,
        "vendor_id": invoice.get("vendor_id"),
        "po_id": invoice.get("po_id"),
        "amount": invoice.get("amount"),
        "department": invoice.get("department"),
        "attack_mode": state.get("attack_mode"),
        "result": None,
        "events": [],
    }

    result = await processor.ainvoke(sub_state)

    # sub_events were already published live by AuthenticatedToolNode; no re-publish needed
    sub_events = result.get("events", [])

    # Record result
    processing_results = dict(state.get("processing_results", {}))
    processing_results[invoice_id] = {
        "status": "processed",
        "vendor_id": invoice.get("vendor_id"),
        "amount": invoice.get("amount"),
        "currency": invoice.get("currency", "USD"),
    }

    return {
        "messages": result.get("messages", [])[-1:],
        "processing_results": processing_results,
        "events": events + sub_events,
    }


async def execute_payment_node(state: APState) -> dict:
    """Invoke the Payment Executor subgraph for the current invoice."""
    invoice_id = state["current_invoice"]
    if not invoice_id:
        return {"messages": [], "events": []}

    result_data = state.get("processing_results", {}).get(invoice_id, {})
    vendor_id = result_data.get("vendor_id", "")
    amount = result_data.get("amount", 0)
    currency = result_data.get("currency", "USD")

    delegate_tools = ["lookup_vendor", "initiate_payment", "approve_payment", "get_fx_rate"]
    await log_delegation("finance-controller", "payment-executor", delegate_tools,
                         invoice_id=invoice_id)
    events = [
        delegation_event("finance-controller", "payment-executor",
                         tools=delegate_tools, ttl_minutes=5),
    ]
    for e in events:
        await publish(e)

    executor = build_payment_executor_graph().compile()
    task_msg = (
        f"Execute payment for invoice {invoice_id}.\n"
        f"Vendor: {vendor_id}, Amount: ${amount} {currency}.\n"
        f"First look up the vendor to get their bank details, then call "
        f"initiate_payment with all the details including bank_account and bank_routing."
    )
    sub_state: PaymentExecutorState = {
        "messages": [HumanMessage(content=task_msg)],
        "warrant": state.get("warrant", ""),
        "invoice_id": invoice_id,
        "vendor_id": result_data.get("vendor_id", ""),
        "amount": result_data.get("amount", 0),
        "currency": result_data.get("currency", "USD"),
        "result": None,
        "events": [],
    }

    result = await executor.ainvoke(sub_state)
    sub_events = result.get("events", [])  # already published live; no re-publish needed

    processing_results = dict(state.get("processing_results", {}))
    if invoice_id in processing_results:
        processing_results[invoice_id]["status"] = "paid"

    return {
        "messages": result.get("messages", [])[-1:],
        "processing_results": processing_results,
        "events": events + sub_events,
    }


def route_after_controller(state: APState) -> str:
    """After the Finance Controller, decide what to do next."""
    current = state.get("current_invoice")
    if not current:
        return END

    results = state.get("processing_results", {})
    invoice_result = results.get(current, {})

    if invoice_result.get("status") == "processed":
        return "execute_payment"
    else:
        return "process_invoice"


def route_after_payment(state: APState) -> str:
    """After payment, go back to controller for next invoice."""
    invoice_batch = state.get("invoice_batch", [])
    processing_results = state.get("processing_results", {})
    pending = [inv for inv in invoice_batch
               if processing_results.get(inv, {}).get("status") != "paid"]

    if pending:
        return "controller"
    return END


def build_ap_graph() -> StateGraph:
    """Build the full AP automation graph."""
    graph = StateGraph(APState)

    graph.add_node("controller", finance_controller_node)
    graph.add_node("process_invoice", process_invoice_node)
    graph.add_node("execute_payment", execute_payment_node)

    graph.set_entry_point("controller")

    graph.add_conditional_edges("controller", route_after_controller)
    graph.add_edge("process_invoice", "execute_payment")
    graph.add_conditional_edges("execute_payment", route_after_payment)

    return graph


app = build_ap_graph().compile()


async def run_demo(
    invoice_ids: list[str] | None = None,
    attack_mode: str | None = None,
    auth_stack: str = "standard",
    warrant_b64: str = "",
) -> dict:
    """Run the demo end-to-end.

    Args:
        invoice_ids: Specific invoices to process, or None for all pending.
        attack_mode: None, "prompt", "injection", or "simulate".
        auth_stack: "standard" or "tenuo".
    """
    run_id = new_run()
    await log_status("system", f"Starting demo run {run_id} (attack={attack_mode})")

    if attack_mode == "injection":
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{VENDOR_PORTAL_URL}/admin/attack/true")
        except httpx.ConnectError:
            pass

    if attack_mode == "simulate":
        from attacks.mode3_simulated_compromise import simulate_attack
        return await simulate_attack()

    initial_state: APState = {
        "messages": [HumanMessage(content="Process pending invoice batch.")],
        "warrant": "",
        "invoice_batch": invoice_ids or [],
        "current_invoice": None,
        "processing_results": {},
        "attack_mode": attack_mode,
        "auth_stack": auth_stack,
        "events": [],
    }

    result = await app.ainvoke(initial_state)

    # Disable injection after run
    if attack_mode == "injection":
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{VENDOR_PORTAL_URL}/admin/attack/false")
        except httpx.ConnectError:
            pass

    return result


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_demo())
