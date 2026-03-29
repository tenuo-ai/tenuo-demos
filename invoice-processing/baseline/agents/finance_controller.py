"""Finance Controller — Level 1 Orchestrator.

Receives invoice batches and fans out to specialist agents. In Tenuo mode,
creates attenuated warrants for each specialist with context-aware constraints
derived from the specific invoice being processed.
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.events import agent_status_event, delegation_event
from agents.llm import get_llm
from agents.prompts import FINANCE_CONTROLLER_PROMPT
from agents.state import APState
from tools.invoice_tools import list_invoices


async def finance_controller_node(state: APState) -> dict:
    """Level 1 orchestrator node.

    Reads the invoice batch and creates dispatch instructions for each invoice.
    The graph router then fans out to the appropriate Level 2 specialist.
    """
    events = [agent_status_event("finance-controller", "started")]

    # If we already have a batch, process it
    invoice_batch = state.get("invoice_batch", [])
    if not invoice_batch:
        # Fetch pending invoices
        result = await list_invoices.ainvoke({"status": "pending"})
        invoices = json.loads(result)
        invoice_batch = [inv["id"] for inv in invoices]
        events.append(agent_status_event("finance-controller", "loaded_batch", count=len(invoice_batch)))

    # Create a processing plan
    processing_results = state.get("processing_results", {})
    pending = [inv_id for inv_id in invoice_batch if inv_id not in processing_results]

    if not pending:
        events.append(agent_status_event("finance-controller", "completed"))
        return {
            "messages": [AIMessage(content=f"All {len(invoice_batch)} invoices processed.")],
            "invoice_batch": invoice_batch,
            "processing_results": processing_results,
            "events": events,
        }

    # Take the next invoice to process
    next_invoice = pending[0]
    events.append(
        agent_status_event("finance-controller", "dispatching", invoice_id=next_invoice)
    )

    return {
        "messages": [
            AIMessage(
                content=f"Dispatching invoice {next_invoice} to Invoice Processor. "
                f"({len(pending)} remaining in batch.)"
            )
        ],
        "invoice_batch": invoice_batch,
        "current_invoice": next_invoice,
        "events": events,
    }
