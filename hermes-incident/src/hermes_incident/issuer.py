"""The incident issuer: the only thing that holds the root key and mints authority.

In production this is your org's control plane (or a Tenuo Cloud trigger). Here
it runs locally. It validates the signed alert, compiles the on-call policy for
the incident (:mod:`hermes_incident.policy`), mints the commander's warrant, and
writes the delegation plan the plugin uses to scope each sub-agent. On
resolution it revokes the incident's authority.

The agent never holds the root key and never influences its own scope: the
warrant is a function of the signed alert and the service catalog alone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from tenuo import AnyOf, All, Regex, SigningKey, Warrant
import tenuo_core

from hermes_incident.policy import Incident, compile_authority, incident_from_alert


class AlertRejected(ValueError):
    """The alert signature did not verify. Nothing is minted."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def verify_alert(body: bytes, signature: str, secret: bytes) -> dict:
    """Check the Alertmanager HMAC and return the first alert, or raise."""
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise AlertRejected("alert HMAC signature did not verify")
    payload = json.loads(body)
    alerts = payload.get("alerts") or []
    if not alerts:
        raise AlertRejected("alert payload carried no alerts")
    return alerts[0]


def _command_constraint(spec: dict):
    """An All([Shlex, AnyOf[Regex...]]) from a {binaries, patterns} spec."""
    members = []
    if spec.get("binaries"):
        members.append(tenuo_core.Shlex(allow=list(spec["binaries"])))
    if spec.get("patterns"):
        members.append(AnyOf([Regex(p) for p in spec["patterns"]]))
    return All(members)


@dataclass(frozen=True)
class IssuedIncident:
    incident: Incident
    warrant_b64: str
    trusted_root_b64: str
    signing_key_b64: str
    plan: dict


class Issuer:
    """Holds the root key for the lab. Mints and revokes incident authority."""

    def __init__(self) -> None:
        self._root = SigningKey.generate()
        self._revoked: set[str] = set()

    @property
    def trusted_root_b64(self) -> str:
        return _b64(self._root.public_key.to_bytes())

    def mint(self, alert: dict) -> IssuedIncident:
        """Validate an alert and mint the commander warrant + delegation plan."""
        inc = incident_from_alert(alert)
        auth = compile_authority(inc)
        agent = SigningKey.generate()
        warrant = (
            Warrant.mint_builder()
            .holder(agent.public_key)
            .capability("terminal", command=_command_constraint(auth["commander"]))
            .capability("delegate_task")
            .ttl(auth["ttl_seconds"])
            .mint(self._root)
        )
        return IssuedIncident(
            incident=inc,
            warrant_b64=_b64(warrant.to_bytes()),
            trusted_root_b64=self.trusted_root_b64,
            signing_key_b64=_b64(agent.secret_key_bytes()),
            plan=auth["plan"],
        )

    def revoke(self, incident_id: str) -> None:
        self._revoked.add(incident_id)

    def is_revoked(self, incident_id: str) -> bool:
        return incident_id in self._revoked


def write_incident(issued: IssuedIncident, home: Path, *, plan_path: Path) -> dict:
    """Write the warrant, plan and signing key where the plugin reads them.

    Returns the ``plugins.entries.hermes-tenuo`` config block to merge into the
    lab profile. The signing key is returned for the caller to place in the
    profile's ``.env`` rather than written to ``config.yaml``.
    """
    home.mkdir(parents=True, exist_ok=True)
    warrant_file = home / f"{issued.incident.incident_id}.warrant"
    warrant_file.write_text(issued.warrant_b64)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(issued.plan, indent=2))
    return {
        "warrant": str(warrant_file),
        "trusted_root": issued.trusted_root_b64,
        "signing_key_env": "TENUO_SIGNING_KEY",
        "delegation_plan": str(plan_path),
        "on_denial": "block",
    }
