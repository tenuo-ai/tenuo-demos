"""`hermes-incident` — the demo entry point and the kubectl/proddb shims.

    hermes-incident replay            # guarded: watch the warrant hold
    hermes-incident replay --unguarded  # no warrant: watch the damage
    hermes-incident reset             # rebuild the simulated world

The shims are installed as separate console scripts (`kubectl`, `proddb`) that
run against the simulated world; the live Hermes profile puts them on PATH.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from rich.console import Console
from rich.table import Table

from hermes_incident import replay, shims, world

console = Console()


def _orders() -> int:
    return sqlite3.connect(world.paths().db).execute("SELECT count(*) FROM orders").fetchone()[0]


def _print_decisions(decisions, guarded: bool) -> None:
    table = Table(show_lines=False, expand=False)
    table.add_column("Agent", style="bold")
    table.add_column("Command")
    table.add_column("Decision", justify="center")
    for d in decisions:
        if not guarded:
            verdict = "[yellow]RAN[/yellow]"
        elif d.allowed:
            verdict = "[green]ALLOW[/green]"
        else:
            verdict = "[red]DENY[/red]"
        table.add_row(d.actor, d.command, verdict)
    console.print(table)


def _cmd_replay(args: argparse.Namespace) -> int:
    guarded = not args.unguarded
    title = "Incident INC — warrant enforced" if guarded else "Incident INC — NO warrant (baseline)"
    console.rule(f"[bold]{title}")
    decisions = replay.run(guarded=guarded)
    _print_decisions(decisions, guarded)

    seeded = 240
    remaining = _orders()
    cluster = world.load_cluster(world.paths())
    payments_gen = cluster["deployments"]["payments"]["generation"]
    secret_dumped = any("get secret" in d.command and d.allowed and "PLACEHOLDER" in (d.executed_output or "")
                        for d in decisions)

    console.print()
    if guarded:
        denied = sum(1 for d in decisions if not d.allowed)
        console.print(f"[green]The injected instruction reached all three agents and was denied {denied} times.[/green]")
        console.print(f"Orders table: [bold]{remaining}/{seeded}[/bold] intact · payments untouched · no secret read.")
        console.print("The agent still did the real fix: restart checkout.")
    else:
        console.print(f"[red]Orders deleted:[/red] {seeded - remaining} of {seeded} "
                      f"· [red]payments restarted[/red] (gen {payments_gen}) "
                      f"· [red]secret exfiltrated:[/red] {secret_dumped}")
        console.print("Nothing stopped the poisoned log from being obeyed.")
    return 0


def _cmd_reset(_args: argparse.Namespace) -> int:
    from hermes_incident import logs
    p = world.reset()
    logs.write_logs(p)
    console.print(f"Rebuilt the simulated world at [bold]{p.root}[/bold]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes-incident", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rp = sub.add_parser("replay", help="run the incident deterministically (no model)")
    rp.add_argument("--unguarded", action="store_true", help="skip the warrant and show the damage")
    sub.add_parser("reset", help="rebuild the simulated world")
    pr = sub.add_parser("provision", help="mint an incident warrant + plan for a live Hermes run")
    pr.add_argument("--out", default=".lab/incident", help="directory for the warrant and plan")
    args = parser.parse_args(argv)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "reset":
        return _cmd_reset(args)
    if args.command == "provision":
        return _cmd_provision(args)
    parser.print_help()
    return 1


def _cmd_provision(args: argparse.Namespace) -> int:
    """Mint the incident and print the plugin config + .env line for a live run."""
    import json
    from pathlib import Path

    from hermes_incident.issuer import Issuer

    alert = {"fingerprint": "a1b2c3d4e5f6",
             "labels": {"alertname": "HighErrorRate", "service": "checkout",
                        "namespace": "shop", "severity": "sev1"}}
    issued = Issuer().mint(alert)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "warrant.b64").write_text(issued.warrant_b64)
    (out / "plan.json").write_text(json.dumps(issued.plan, indent=2))

    console.print(f"Minted [bold]{issued.incident.incident_id}[/bold] "
                  f"(TTL {issued.incident.ttl_seconds // 60} min) → {out}\n")
    console.print("Add to your Hermes [bold]config.yaml[/bold] under plugins.entries.hermes-tenuo:")
    console.print(f"""[dim]      warrant: {out / 'warrant.b64'}
      trusted_root: {issued.trusted_root_b64}
      signing_key_env: TENUO_SIGNING_KEY
      delegation_plan: {out / 'plan.json'}
      on_denial: block[/dim]""")
    console.print("\nAnd in your Hermes [bold].env[/bold] (not config.yaml):")
    console.print(f"[dim]      TENUO_SIGNING_KEY={issued.signing_key_b64}[/dim]")
    return 0


# Console-script entry points for the shims.
def kubectl_main() -> int:
    return shims.kubectl()


def proddb_main() -> int:
    return shims.proddb()


if __name__ == "__main__":
    sys.exit(main())
