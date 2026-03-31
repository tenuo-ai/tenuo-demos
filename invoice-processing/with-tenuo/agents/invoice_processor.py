"""Invoice Processor — Level 2 Specialist.

Processes a single invoice: reads it, verifies vendor, checks PO, approves.
This is the primary attack target — the invoice notes field may contain
an injection payload that tricks the agent into updating vendor bank details.

In Tenuo mode, this agent receives an attenuated warrant scoped to the
specific invoice, vendor, and amount. The Level 3 Vendor Verification
subagent gets an even narrower warrant without `update_vendor_bank`.
"""

import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from auth.tool_node import AuthenticatedToolNode
from agents.events import agent_status_event
from agents.llm import get_llm
from agents.logger import log_thinking, log_status
from agents.prompts import (
    INVOICE_PROCESSOR_COMPROMISED_PROMPT,
    INVOICE_PROCESSOR_PROMPT,
)
from agents.state import InvoiceProcessorState
from tools.invoice_tools import approve_invoice, read_invoice, read_po
from tools.vendor_tools import lookup_vendor, update_vendor_bank, verify_vendor

# All tools available to the Invoice Processor (pre-Tenuo)
INVOICE_PROCESSOR_TOOLS = [
    read_invoice,
    read_po,
    lookup_vendor,
    verify_vendor,
    update_vendor_bank,  # THE ATTACK TARGET — Tenuo removes this from Level 3
    approve_invoice,
]


def _get_system_prompt(state: InvoiceProcessorState) -> str:
    """Return system prompt — compromised if attack mode is 'prompt'."""
    if state.get("attack_mode") == "prompt":
        return INVOICE_PROCESSOR_COMPROMISED_PROMPT
    return INVOICE_PROCESSOR_PROMPT


async def invoice_processor_agent(state: InvoiceProcessorState, config: RunnableConfig | None = None) -> dict:
    """The LLM-powered invoice processing node."""
    llm = get_llm()
    llm_with_tools = llm.bind_tools(INVOICE_PROCESSOR_TOOLS)

    system_prompt = _get_system_prompt(state)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await llm_with_tools.ainvoke(messages)

    # Log LLM reasoning to activity feed
    if response.content:
        await log_thinking("invoice-processor", response.content, invoice_id=state["invoice_id"])
    if response.tool_calls:
        for tc in response.tool_calls:
            await log_status("invoice-processor",
                             f"Calling {tc['name']}",
                             invoice_id=state["invoice_id"])

    events = [
        agent_status_event(
            "invoice-processor",
            "llm_response",
            invoice_id=state["invoice_id"],
            has_tool_calls=bool(response.tool_calls),
        )
    ]

    return {"messages": [response], "events": events}


def should_continue(state: InvoiceProcessorState) -> str:
    """Route: if the last message has tool calls, go to tools. Otherwise end."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_invoice_processor_graph(use_tenuo: bool = False) -> StateGraph:
    """Build the Level 2 Invoice Processor subgraph."""
    if use_tenuo:
        from auth.tenuo_tool_node import TenuoAuthenticatedToolNode
        if os.environ.get("TENUO_MODE", "local") == "cloud":
            from auth.tenuo_integration import build_tenuo_tool_node
            inner = build_tenuo_tool_node(INVOICE_PROCESSOR_TOOLS)
        else:
            from auth.tenuo_local import build_tenuo_tool_node_local, KEY_PROCESSOR
            inner = build_tenuo_tool_node_local(INVOICE_PROCESSOR_TOOLS, key_id=KEY_PROCESSOR)
        tool_node = TenuoAuthenticatedToolNode(inner, agent_id="invoice-processor")
    else:
        tool_node = AuthenticatedToolNode(INVOICE_PROCESSOR_TOOLS, agent_id="invoice-processor")

    graph = StateGraph(InvoiceProcessorState)
    graph.add_node("agent", invoice_processor_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph
