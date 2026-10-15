"""Compile a signed alert + the service catalog + an on-call policy into authority.

The same rendering produces the commander's warrant and the delegation plan,
so the plan's ``root`` always matches what was signed. Every value in a warrant
comes from the signed alert or the service catalog — never from anything an
agent reads or says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

# Alert label values must be plain identifiers. This is the first gate: an
# attacker who can influence an alert label cannot smuggle regex or shell
# metacharacters into a warrant. service/namespace follow Kubernetes DNS-label
# rules (lowercase); alertname is a Prometheus rule name (mixed case).
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ALERTNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SEVERITY = re.compile(r"^[a-z0-9]{1,16}$")
FINGERPRINT = re.compile(r"^[0-9a-f]{8,32}$")
_LABEL_RULES = {"alertname": ALERTNAME, "service": NAME, "namespace": NAME, "severity": SEVERITY}


class PolicyRefusal(ValueError):
    """The alert does not entitle anyone to authority. No warrant is minted."""


@dataclass(frozen=True)
class Incident:
    incident_id: str
    service: str
    namespace: str
    severity: str
    deps: tuple
    ttl_seconds: int
    policy_name: str


def _data(name: str) -> Any:
    return yaml.safe_load(
        resources.files("hermes_incident").joinpath("data").joinpath(name).read_text()
    )


def load_catalog() -> dict:
    return _data("catalog.yaml")


def load_policy(name: str = "high-5xx") -> dict:
    return _data(f"policies/{name}.yaml")


def incident_from_alert(alert: dict, *, catalog: dict | None = None,
                        policy: dict | None = None, policy_name: str = "high-5xx") -> Incident:
    """Validate one Alertmanager alert and resolve it against the catalog.

    Raises PolicyRefusal unless the alert is well-formed, names a known service
    in its real namespace, and matches a configured on-call policy.
    """
    catalog = catalog if catalog is not None else load_catalog()
    policy = policy if policy is not None else load_policy(policy_name)
    labels = alert.get("labels") or {}

    for key, rule in _LABEL_RULES.items():
        value = labels.get(key)
        if not isinstance(value, str) or not rule.match(value):
            raise PolicyRefusal(f"label {key!r} is missing or not a plain identifier")

    if labels["alertname"] != policy["match"]["alertname"]:
        raise PolicyRefusal(f"no on-call policy matches alert {labels['alertname']!r}")

    service = catalog["services"].get(labels["service"])
    if service is None:
        raise PolicyRefusal(f"service {labels['service']!r} is not in the service catalog")
    if labels["namespace"] != catalog["namespace"]:
        raise PolicyRefusal(
            f"service {labels['service']!r} does not run in namespace {labels['namespace']!r}"
        )

    ttl_minutes = policy["ttl_minutes_by_severity"].get(labels["severity"])
    if ttl_minutes is None:
        raise PolicyRefusal(f"severity {labels['severity']!r} has no on-call TTL")

    fingerprint = str(alert.get("fingerprint") or "")
    if not FINGERPRINT.match(fingerprint):
        raise PolicyRefusal("alert fingerprint is missing or malformed")

    return Incident(
        incident_id=f"INC-{int(fingerprint[:8], 16) % 10000:04d}",
        service=labels["service"],
        namespace=labels["namespace"],
        severity=labels["severity"],
        deps=tuple(service.get("depends_on") or ()),
        ttl_seconds=int(ttl_minutes) * 60,
        policy_name=policy_name,
    )


_FRAGMENT = re.compile(r"\{([A-Z][A-Z_]*)\}")


def _expand_fragments(pattern: str, fragments: dict) -> str:
    """Expand {UPPERCASE} fragment names (nested allowed, depth-limited)."""
    for _ in range(8):
        expanded = _FRAGMENT.sub(lambda m: fragments[m.group(1)], pattern)
        if expanded == pattern:
            return pattern
        pattern = expanded
    raise ValueError("policy fragments nest too deeply")


def _render(pattern: str, inc: Incident, fragments: dict | None = None) -> str:
    """Fill fragments, then {service}, {namespace}, {deps} in one command pattern.

    {deps} becomes a regex alternation of the service's catalog dependencies.
    A pattern that references {deps} when the service has none is dropped — a
    leaf service grants no dependency-read rule rather than an empty one.
    """
    pattern = _expand_fragments(pattern, fragments or {})
    if "{deps}" in pattern and not inc.deps:
        return ""
    deps_alt = "|".join(re.escape(d) for d in inc.deps)
    return (pattern
            .replace("{service}", re.escape(inc.service))
            .replace("{namespace}", re.escape(inc.namespace))
            .replace("{deps}", deps_alt))


def _role_spec(role: dict, inc: Incident, fragments: dict | None = None) -> dict:
    """One role's {binaries, patterns}, rendered for this incident."""
    patterns = [p for p in (_render(c, inc, fragments) for c in role.get("commands", [])) if p]
    return {"binaries": list(role.get("binaries", [])), "patterns": patterns}


def compile_authority(inc: Incident, policy: dict | None = None) -> dict:
    """Return {"commander": {...capability args...}, "plan": {...delegation plan...}}.

    The commander warrant and the delegation-plan levels are rendered from the
    same policy roles, so the plan's root matches the minted warrant exactly.
    """
    policy = policy if policy is not None else load_policy(inc.policy_name)
    roles = policy["roles"]
    fragments = policy.get("fragments") or {}
    commander = _role_spec(roles["commander"], inc, fragments)
    investigator = _role_spec(roles["investigator"], inc, fragments)
    inspector = _role_spec(roles["inspector"], inc, fragments)

    def tool_entry(spec: dict, *, delegates: bool = True) -> dict:
        # The command is what carries authority, so it is the one argument
        # checked. Hermes's terminal tool sends other arguments only on some
        # calls (timeout, workdir, pty), and a named argument is required, so
        # those are allowed unnamed rather than listed. Tighten this once
        # optional-argument constraints land (tenuo-ai/tenuo#910).
        terminal = {"command": spec, "_allow_unknown": True}
        entry = {"terminal": terminal}
        if delegates:
            entry["delegate_task"] = {}
        return entry

    frac = lambda role: policy["roles"][role].get("ttl_fraction", 1.0)
    plan = {
        "version": 1,
        "root": {"tools": tool_entry(commander)},
        "levels": [
            {"ttl_seconds": int(inc.ttl_seconds * frac("investigator")),
             "tools": tool_entry(investigator)},
            {"ttl_seconds": int(inc.ttl_seconds * frac("inspector")),
             "tools": tool_entry(inspector, delegates=False)},
        ],
    }
    return {"commander": commander, "plan": plan, "ttl_seconds": inc.ttl_seconds}
