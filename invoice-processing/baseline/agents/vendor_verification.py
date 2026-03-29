"""Vendor Verification — Level 3 Sub-specialist.

Spawned by Invoice Processor to verify vendor details. This agent has
the narrowest warrant in the chain:
- Level 1 (Finance Controller): all tools
- Level 2 (Invoice Processor): invoice + vendor tools including update_vendor_bank
- Level 3 (Vendor Verification): ONLY lookup_vendor and verify_vendor

The key demo point: even if this agent is compromised, it physically
cannot call update_vendor_bank because the tool isn't in its warrant.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from agents.events import agent_status_event
from agents.llm import get_llm
from agents.prompts import VENDOR_VERIFICATION_PROMPT
from agents.state import VendorVerificationState
from auth.tool_node import AuthenticatedToolNode
from tools.vendor_tools import lookup_vendor, verify_vendor

# Level 3 tools — deliberately NO update_vendor_bank
VENDOR_VERIFICATION_TOOLS = [lookup_vendor, verify_vendor]


async def vendor_verification_agent(state: VendorVerificationState, config: RunnableConfig | None = None) -> dict:
    """The LLM-powered vendor verification node."""
    llm = get_llm()
    llm_with_tools = llm.bind_tools(VENDOR_VERIFICATION_TOOLS)

    messages = [SystemMessage(content=VENDOR_VERIFICATION_PROMPT)] + state["messages"]

    if len(state["messages"]) <= 1:
        task_msg = HumanMessage(
            content=f"Verify vendor {state['vendor_id']}. "
            f"Look up their details and confirm their verification status."
        )
        messages.append(task_msg)

    response = await llm_with_tools.ainvoke(messages)

    events = [
        agent_status_event(
            "vendor-verification",
            "llm_response",
            vendor_id=state["vendor_id"],
            has_tool_calls=bool(response.tool_calls),
        )
    ]

    return {"messages": [response], "events": events}


def should_continue(state: VendorVerificationState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def build_vendor_verification_graph() -> StateGraph:
    """Build the Level 3 Vendor Verification subgraph."""
    tool_node = AuthenticatedToolNode(
        VENDOR_VERIFICATION_TOOLS,
        agent_id="vendor-verification",
        
    )

    graph = StateGraph(VendorVerificationState)
    graph.add_node("agent", vendor_verification_agent)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph
