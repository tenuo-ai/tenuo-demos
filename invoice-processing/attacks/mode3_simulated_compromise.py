"""Attack Mode 3: Simulated Compromise.

100% reliable fallback for live demos. Bypasses the LLM entirely and
directly issues malicious tool calls through the auth stack. This
demonstrates what happens when an agent IS compromised (regardless of how).

In standard mode: all 4 auth layers approve — the attack succeeds.
In Tenuo mode: warrant constraint check blocks it — 🛡 not in task delegation.
"""

import os
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from attacks.payloads import ATTACKER_BANK_ACCOUNT, ATTACKER_BANK_ROUTING
from auth.pipeline import evaluate_all_layers
from tools.vendor_tools import update_vendor_bank


def _cloud_mode() -> bool:
    return os.environ.get("TENUO_MODE", "local") == "cloud"


async def _attenuate_for_invoice_processor(root_warrant_b64: str, vendor_id: str) -> str:
    if _cloud_mode():
        from auth.tenuo_integration import attenuate_for_invoice_processor_cloud
        return await attenuate_for_invoice_processor_cloud(root_warrant_b64)
    from auth.tenuo_local import attenuate_for_invoice_processor
    return await attenuate_for_invoice_processor(root_warrant_b64, "sim", vendor_id)


def _build_invoice_processor_tool_graph(agent_id: str):
    """The Tenuo tool node the Invoice Processor uses in a real Act 3 run.

    Wrapped in a one-node graph because LangGraph's ToolNode needs the
    runtime config a graph provides.
    """
    from langgraph.graph import END, StateGraph

    from agents.invoice_processor import INVOICE_PROCESSOR_TOOLS
    from agents.state import InvoiceProcessorState
    from auth.tenuo_tool_node import TenuoAuthenticatedToolNode

    if _cloud_mode():
        from auth.tenuo_integration import build_tenuo_tool_node
        inner = build_tenuo_tool_node(INVOICE_PROCESSOR_TOOLS)
    else:
        from auth.tenuo_local import KEY_PROCESSOR, build_tenuo_tool_node_local
        inner = build_tenuo_tool_node_local(INVOICE_PROCESSOR_TOOLS, key_id=KEY_PROCESSOR)

    graph = StateGraph(InvoiceProcessorState)
    graph.add_node("tools", TenuoAuthenticatedToolNode(inner, agent_id=agent_id))
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    return graph.compile()


async def simulate_attack(
    agent_id: str = "invoice-processor",
    vendor_id: str = "V-4521",
    auth_stack: str = "standard",
    warrant_b64: str = "",
) -> dict[str, Any]:
    """Directly execute the attack and return auth decisions.

    Bypasses the LLM and calls tools directly. In Tenuo mode, attenuates
    the warrant for invoice-processor (which removes update_vendor_bank) and
    sends the call through the same Tenuo tool node a real run uses —
    demonstrating cryptographic enforcement without LLM involvement.
    """
    from agents.logger import log_status, log_tool_call, log_tool_result, log_event
    from server.events import publish

    await log_status("system", "Starting simulated attack (LLM bypassed — direct tool calls)")

    results = {"steps": []}

    update_args = {
        "vendor_id": vendor_id,
        "bank_account": ATTACKER_BANK_ACCOUNT,
        "bank_routing": ATTACKER_BANK_ROUTING,
        "reason": "Per corporate restructuring notice - updated remittance instructions CR-2026-0891",
    }

    await log_tool_call(agent_id, "update_vendor_bank", update_args)

    # --- Tenuo path: send the call through the Invoice Processor's real tool node ---
    if auth_stack == "tenuo" and warrant_b64:
        executed = False
        try:
            proc_warrant_b64 = await _attenuate_for_invoice_processor(warrant_b64, vendor_id)
        except Exception:
            # Fail closed: never fall back to the root warrant.
            await log_event(agent_id, "tenuo_block",
                            content="Blocked: update_vendor_bank · warrant attenuation failed",
                            tool_name="update_vendor_bank")
        else:
            # The same node a real Act 3 run uses: the SDK authorizes the call
            # (signature, expiry, tools, constraints) and the node logs the
            # standard layers and the Tenuo decision for the dashboard.
            call_id = "simulated-update-vendor-bank"
            tool_graph = _build_invoice_processor_tool_graph(agent_id)
            out = await tool_graph.ainvoke({
                "messages": [AIMessage(content="", tool_calls=[
                    {"name": "update_vendor_bank", "args": update_args, "id": call_id},
                ])],
                "warrant": proc_warrant_b64,
            })
            executed = any(
                isinstance(m, ToolMessage) and m.tool_call_id == call_id
                and getattr(m, "status", None) != "error"
                for m in out.get("messages", [])
            )

        blocked = not executed
        results["attack_success"] = executed
        results["message"] = (
            "Attack succeeded (warrant check passed — unexpected)."
            if executed
            else "Tenuo blocked the attack. update_vendor_bank was not in the task delegation."
        )

        await log_status("system", results["message"])
        results["steps"].append({"tool": "update_vendor_bank", "args": update_args, "blocked": blocked})
        return results

    # --- Standard path: all 4 layers evaluate, tool executes ---
    await log_status(agent_id, "Calling update_vendor_bank with attacker bank details",
                     tool_name="update_vendor_bank")

    decisions = await evaluate_all_layers(agent_id, "update_vendor_bank", update_args)
    all_allowed = all(d.allowed for d in decisions)

    for d in decisions:
        await publish({
            "type": "auth_decision",
            "agent_id": agent_id,
            "tool_name": "update_vendor_bank",
            "layer": d.layer,
            "decision": "allow" if d.allowed else "deny",
            "reason": d.reason,
            "latency_us": d.latency_us,
        })

    step1 = {
        "tool": "update_vendor_bank",
        "args": update_args,
        "decisions": [{"layer": d.layer, "allowed": d.allowed, "reason": d.reason} for d in decisions],
        "all_allowed": all_allowed,
    }

    if all_allowed:
        result = await update_vendor_bank.ainvoke(update_args)
        step1["result"] = result
        await log_tool_result(agent_id, "update_vendor_bank", str(result))
        await log_status(agent_id,
            "⚠ Bank details updated to attacker account. Next payment will go to attacker.",
            tool_name="update_vendor_bank")

    results["steps"].append(step1)
    results["attack_success"] = all_allowed
    results["message"] = (
        "All 4 auth layers approved the bank detail change. "
        "Next payment to this vendor will go to the attacker's account."
        if all_allowed
        else "Auth stack blocked the attack (unexpected in standard mode)."
    )

    await log_status("system", results["message"])
    return results
