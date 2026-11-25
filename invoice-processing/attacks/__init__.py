"""Attack modes for the demo, keyed by the value the dashboard sends."""

ATTACK_LABELS: dict[str | None, str] = {
    None: "no attack",
    "injection": "poisoned invoice (fake bank-change note in the invoice)",
    "prompt": "tampered instructions (attacker edited the Invoice Processor's system prompt)",
    "simulate": "simulated compromise (LLM bypassed, malicious call sent directly)",
}


def describe_attack(attack_mode: str | None) -> str:
    """Human-readable label for an attack mode, for the activity feed."""
    return ATTACK_LABELS.get(attack_mode, str(attack_mode))
