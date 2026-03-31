"""Attack Mode 3: Simulated Compromise.

100% reliable fallback for live demos. Bypasses the LLM entirely and
directly issues malicious tool calls through the auth stack. This
demonstrates what happens when an agent IS compromised (regardless of how)
and shows that all 4 auth layers approve the attack.

Use this when:
- Model updates break indirect injection
- You need guaranteed demo reliability
- You want to focus on the auth failure, not the injection technique
"""

from typing import Any

from attacks.payloads import ATTACKER_BANK_ACCOUNT, ATTACKER_BANK_ROUTING
from auth.pipeline import evaluate_all_layers
from tools.vendor_tools import update_vendor_bank


async def simulate_attack(
    agent_id: str = "invoice-processor",
    vendor_id: str = "V-4521",
) -> dict[str, Any]:
    """Directly execute the attack and return auth decisions.

    This bypasses the LLM and calls tools directly, showing that the
    auth stack approves every step of the attack.
    """
    results = {"steps": []}

    # Step 1: Update vendor bank details (the malicious action)
    update_args = {
        "vendor_id": vendor_id,
        "bank_account": ATTACKER_BANK_ACCOUNT,
        "bank_routing": ATTACKER_BANK_ROUTING,
        "reason": "Per corporate restructuring notice - updated remittance instructions CR-2026-0891",
    }

    decisions = await evaluate_all_layers(agent_id, "update_vendor_bank", update_args)
    all_allowed = all(d.allowed for d in decisions)

    step1 = {
        "tool": "update_vendor_bank",
        "args": update_args,
        "decisions": [{"layer": d.layer, "allowed": d.allowed, "reason": d.reason} for d in decisions],
        "all_allowed": all_allowed,
    }

    if all_allowed:
        result = await update_vendor_bank.ainvoke(update_args)
        step1["result"] = result

    results["steps"].append(step1)

    # Step 2: Now payment will go to the attacker's account
    # (This would normally be handled by the Payment Executor agent)
    results["attack_success"] = all_allowed
    results["message"] = (
        "All 4 auth layers approved the bank detail change. "
        "Next payment to this vendor will go to the attacker's account."
        if all_allowed
        else "Auth stack blocked the attack (unexpected in standard mode)."
    )

    return results
