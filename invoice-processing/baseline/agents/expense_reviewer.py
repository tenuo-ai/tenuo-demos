"""Expense Reviewer — Level 2 Specialist.

Reviews expense invoices for anomalies and either approves or flags them.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from agents.llm import get_llm
from agents.prompts import EXPENSE_REVIEWER_PROMPT
from agents.state import InvoiceProcessorState  # Reuse same shape
from auth.tool_node import AuthenticatedToolNode
from tools.invoice_tools import read_invoice, read_po
from tools.review_tools import approve_expense, flag_expense

EXPENSE_REVIEWER_TOOLS = [read_invoice, read_po, approve_expense, flag_expense]


async def expense_reviewer_agent(state: InvoiceProcessorState, config: RunnableConfig | None = None) -> dict:
    llm = get_llm()
    llm_with_tools = llm.bind_tools(EXPENSE_REVIEWER_TOOLS)

    messages = [SystemMessage(content=EXPENSE_REVIEWER_PROMPT)] + state["messages"]

    if len(state["messages"]) <= 1:
        task_msg = HumanMessage(
            content=f"Review expense invoice {state['invoice_id']}. "
            f"Check the PO match and flag anything suspicious."
        )
        messages.append(task_msg)

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response], "events": []}


def should_continue(state: InvoiceProcessorState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_expense_reviewer_graph() -> StateGraph:
    tool_node = AuthenticatedToolNode(
        EXPENSE_REVIEWER_TOOLS,
        agent_id="expense-reviewer",
        
    )

    graph = StateGraph(InvoiceProcessorState)
    graph.add_node("agent", expense_reviewer_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph
