"""FX Rate Checker — Level 3 Sub-specialist.

Spawned by Payment Executor for international payments. Simple read-only
agent that looks up exchange rates.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from agents.llm import get_llm
from agents.prompts import FX_RATE_CHECKER_PROMPT
from agents.state import FXRateState
from auth.tool_node import AuthenticatedToolNode
from tools.payment_tools import get_fx_rate

FX_RATE_TOOLS = [get_fx_rate]


async def fx_rate_agent(state: FXRateState, config: RunnableConfig | None = None) -> dict:
    llm = get_llm()
    llm_with_tools = llm.bind_tools(FX_RATE_TOOLS)

    messages = [SystemMessage(content=FX_RATE_CHECKER_PROMPT)] + state["messages"]

    if len(state["messages"]) <= 1:
        task_msg = HumanMessage(
            content=f"Get the current exchange rate from {state['from_currency']} to {state['to_currency']}."
        )
        messages.append(task_msg)

    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response], "events": []}


def should_continue(state: FXRateState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_fx_rate_graph() -> StateGraph:
    tool_node = AuthenticatedToolNode(
        FX_RATE_TOOLS,
        agent_id="fx-rate-checker",
        
    )

    graph = StateGraph(FXRateState)
    graph.add_node("agent", fx_rate_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph
