"""Attack Mode 3: Simulated Compromise.

100% reliable fallback for live demos. Bypasses the LLM entirely and
directly issues malicious tool calls through the auth stack. This
demonstrates what happens when an agent IS compromised (regardless of how).

In standard mode: all 4 auth layers approve — the attack succeeds.
In Tenuo mode: warrant constraint check blocks it — 🛡 not in task delegation.
"""

from typing import Any

from attacks.payloads import ATTACKER_BANK_ACCOUNT, ATTACKER_BANK_ROUTING
from auth.pipeline import evaluate_all_layers
from tools.vendor_tools import update_vendor_bank


async def simulate_attack(
    agent_id: str = "invoice-processor",
    vendor_id: str = "V-4521",
    auth_stack: str = "standard",
    warrant_b64: str = "",
) -> dict[str, Any]:
    """Directly execute the attack and return auth decisions.

    Bypasses the LLM and calls tools directly. In Tenuo mode, attenuates
    the warrant for invoice-processor (which removes update_vendor_bank) and
    runs the warrant constraint check — demonstrating cryptographic enforcement
    without LLM involvement.
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

    # --- Tenuo path: attenuate warrant and check constraints ---
    if auth_stack == "tenuo" and warrant_b64:
        import os
        try:
            if os.environ.get("TENUO_MODE", "local") == "cloud":
                from auth.tenuo_integration import attenuate_for_invoice_processor_cloud
                proc_warrant_b64 = await attenuate_for_invoice_processor_cloud(warrant_b64)
            else:
                from auth.tenuo_local import attenuate_for_invoice_processor
                proc_warrant_b64 = await attenuate_for_invoice_processor(warrant_b64, "sim", vendor_id)

            from tenuo_core import Warrant
            w = Warrant.from_base64(proc_warrant_b64)
            blocked = False
            try:
                w.check_constraints("update_vendor_bank", update_args)
            except Exception:
                blocked = True

        except Exception as e:
            blocked = True  # Fail closed

        # Run standard layers for display (all show ALLOW as usual)
        decisions = await evaluate_all_layers(agent_id, "update_vendor_bank", update_args)
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

        if blocked:
            await log_event(agent_id, "tenuo_block",
                            content="Blocked: update_vendor_bank · not in task delegation",
                            tool_name="update_vendor_bank")
            results["attack_success"] = False
            results["message"] = "Tenuo blocked the attack. update_vendor_bank was not in the task delegation."
        else:
            result = await update_vendor_bank.ainvoke(update_args)
            await log_tool_result(agent_id, "update_vendor_bank", str(result))
            results["attack_success"] = True
            results["message"] = "Attack succeeded (warrant check passed — unexpected)."

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
