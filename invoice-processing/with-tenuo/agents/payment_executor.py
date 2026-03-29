"""Payment Executor — Level 2 Specialist.

Executes payment for approved invoices. This is where the attack becomes
visible: if the injection changed vendor bank details, the payment goes
to the attacker's account.
"""

import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from auth.tool_node import AuthenticatedToolNode
from agents.events import agent_status_event
from agents.llm import get_llm
from agents.logger import log_thinking, log_status
from agents.prompts import PAYMENT_EXECUTOR_PROMPT
from agents.state import PaymentExecutorState
from tools.payment_tools import approve_payment, get_fx_rate, initiate_payment
from tools.vendor_tools import lookup_vendor

PAYMENT_EXECUTOR_TOOLS = [lookup_vendor, initiate_payment, approve_payment, get_fx_rate]


async def payment_executor_agent(state: PaymentExecutorState, config: RunnableConfig | None = None) -> dict:
    """The LLM-powered payment execution node."""
    llm = get_llm()
    llm_with_tools = llm.bind_tools(PAYMENT_EXECUTOR_TOOLS)

    messages = [SystemMessage(content=PAYMENT_EXECUTOR_PROMPT)] + state["messages"]
    response = await llm_with_tools.ainvoke(messages)

    if response.content:
        await log_thinking("payment-executor", response.content, invoice_id=state["invoice_id"])
    if response.tool_calls:
        for tc in response.tool_calls:
            await log_status("payment-executor", f"Calling {tc['name']}")

    events = [
        agent_status_event(
            "payment-executor",
            "llm_response",
            invoice_id=state["invoice_id"],
            has_tool_calls=bool(response.tool_calls),
        )
    ]

    return {"messages": [response], "events": events}


def should_continue(state: PaymentExecutorState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_payment_executor_graph(use_tenuo: bool = False) -> StateGraph:
    """Build the Level 2 Payment Executor subgraph."""
    if use_tenuo:
        from auth.tenuo_tool_node import TenuoAuthenticatedToolNode
        from auth.tenuo_local import build_tenuo_tool_node_local, KEY_PAYMENT
        inner = build_tenuo_tool_node_local(PAYMENT_EXECUTOR_TOOLS, key_id=KEY_PAYMENT)
        tool_node = TenuoAuthenticatedToolNode(inner, agent_id="payment-executor")
    else:
        tool_node = AuthenticatedToolNode(PAYMENT_EXECUTOR_TOOLS, agent_id="payment-executor")

    graph = StateGraph(PaymentExecutorState)
    graph.add_node("agent", payment_executor_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph
