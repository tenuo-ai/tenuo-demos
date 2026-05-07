# AI On-Call SRE Agent with Cryptographic Authorization

A production-shaped demo of an AI agent that triages and remediates incidents under task-scoped authority, with human-in-the-loop approval for elevated actions and a cryptographic receipt chain for every step.

## What this demo shows

An AI on-call agent receives a PagerDuty-style alert and runs a Temporal workflow that investigates and remediates the incident. Three Tenuo properties are demonstrated as load-bearing in production:

1. **Task-scoped authority.** The agent receives a fresh warrant minted for *this incident only*, scoped to the alert's risk profile (severity, environment, capability set). The warrant has a TTL matched to the SLA window and expires when the incident closes.

2. **HITL with cryptographic approval.** The warrant declares `approval_gates` for elevated actions (`restart_service[production]`). The activity inbound raises `ApprovalGateTriggered` until a `SignedApproval` artifact (Ed25519 over CBOR) is attached. The on-call lead signs the approval via a local web UI; `tenuo_core.verify_approvals` checks the signature, the request-hash binding, and the approver's pubkey against the warrant's `required_approvers` before dispatching.

3. **Cryptographic receipts.** Every action produces a structured event with cryptographic provenance: incident-warrant signed by the on-call lead, signed approval verified before each elevated dispatch, denials labeled with the violated constraint. The chain is offline-verifiable against trusted issuer keys.

A bonus scenario demonstrates that **the same warrant model that scopes the agent also defends against indirect prompt injection** — when a tainted log line tries to coerce the agent into destructive actions, structurally-blocked tools (`delete_database`, `modify_iam`) are denied at the warrant boundary, and the operator (modeled as auto-rejecting after seeing the prior denials) refuses the production-restart approval.

## Architecture

```
┌──────────────────────┐     ┌──────────────────────┐
│  Alert Handler       │────▶│  Temporal Workflow   │
│  (mints warrant      │     │  IncidentResponse    │
│   for this incident) │     │  (orchestrator)      │
└──────────────────────┘     └──────────┬───────────┘
                                        │
                ┌───────────────────────┼───────────────────────┐
                │                       │                       │
                ▼                       ▼                       ▼
       ┌────────────────┐     ┌────────────────┐     ┌────────────────┐
       │  Activities    │     │  Approval UI   │     │  Audit          │
       │  (per-tool;    │     │  (FastAPI,     │     │  (terminal +    │
       │   warrant +    │     │   signs        │     │   receipt       │
       │   PoP verified │     │   Ed25519      │     │   chain)        │
       │   inbound)     │     │   approvals)   │     │                 │
       └───────┬────────┘     └────────────────┘     └────────────────┘
               │
               ▼
       ┌────────────────┐
       │  Tools layer   │
       │  (cloud sim +  │
       │   in-proc MCP) │
       └────────────────┘
```

The workflow orchestrates the incident response. Each tool call is a Temporal activity. Tenuo's `TenuoActivityInboundInterceptor` verifies the warrant + PoP at the activity inbound; for activities matching `approval_gates`, it additionally checks attached SignedApprovals via `tenuo_core.verify_approvals`.

## Layout

Four Python files, each with one obvious concern:

```
workflow.py      Workflow + activities + agent + warrant policy + audit
tools.py         MCP server + cloud simulator (the simulated infrastructure)
approval_ui.py   FastAPI HITL approval UI (launched in-process by run.py)
run.py           Entry point: alert handler, worker, workflow kickoff, UI
```

Plus `fixtures/alert.json` (the alert payload) and `fixtures/cassette.json` (recorded LLM responses for offline runs).

## Quickstart

Two things need to be running. One terminal for the Temporal dev server, one for the demo.

**Terminal A** (leave running):

```bash
temporal server start-dev
```

**Terminal B**:

```bash
make setup            # one-time: creates .venv, installs deps
make demo             # runs the nominal scenario with live HITL approval
```

`make demo` starts the workflow and the approval UI together in one process. When the agent hits the production-restart gate, the workflow waits and prints:

```
  ┌─────────────────────────────────────────────────┐
  │  Approval UI live at http://localhost:5050      │
  │  Open it when the agent requests approval.      │
  └─────────────────────────────────────────────────┘
```

Open that URL, click **Sign and approve** on the pending card, and the workflow continues. The receipt chain prints when it completes.

**Other targets:**

```bash
make demo-injection         # injection scenario with live UI (you click Reject)
make demo-auto              # nominal scenario, simulated operator (auto-approve, no UI needed)
make demo-auto-injection    # injection scenario, simulated operator (auto-reject, no UI needed)
```

Use `make demo-auto*` for CI or smoke tests. Use `make demo` / `make demo-injection` to actually feel the cryptographic HITL flow.

Prerequisites:
- Python 3.11+
- Temporal CLI (`brew install temporal`, then `temporal server start-dev`)
- Optional: `ANTHROPIC_API_KEY` for live LLM. Without it, a recorded cassette is replayed (the demo is fully runnable offline).

## Expected output: nominal

```
═══════════════════════════════════════════════════════════════════
  TASK-SCOPED WARRANT MINTED — Incident IR-2026-04-29-0481
═══════════════════════════════════════════════════════════════════
  Session ID:     incident-IR-2026-04-29-0481
  Holder:         ai-oncall-agent-001
  Severity / TTL: high, 60m
  GRANTED:
    ✓ read_logs                 service=Wildcard(), window=Wildcard()
    ✓ read_metrics              metric=Wildcard(), service=Wildcard(), …
    ✓ restart_service           environment=Wildcard(), name=Wildcard()
    ✓ scale_service             environment=Wildcard(), name=Wildcard(), …
    ✓ post_status               channel=OneOf([#sre-alerts, #status-updates])
    ✓ escalate                  level=OneOf([low, medium])
═══════════════════════════════════════════════════════════════════

  [agent]    decided: read_logs(payment-service-prod, 5min)
  [tool ✓]   read_logs                 ALLOWED
  [agent]    decided: read_metrics(cpu, 30min)
  [tool ✓]   read_metrics              ALLOWED
  [agent]    decided: read_metrics(error_rate, 30min)  // spike correlates with deploy
  [tool ✓]   read_metrics              ALLOWED
  [agent]    decided: restart_service(payment-service-prod, production)
  [gate]     restart_service           approval_gate triggered (warrant requires HITL)
  [hitl]     awaiting human approval  http://localhost:5050/approvals/IR-2026-04-29-0481-001
  [auto-approve] granting IR-2026-04-29-0481-001 for restart_service(production)
  [hitl ✓]   approval IR-2026-04-29-0481-001 granted by operator
  [tool ✓]   restart_service           ALLOWED (signed approval verified)
  [agent]    decided: post_status(#sre-alerts, "...recovering.")
  [tool ✓]   post_status               ALLOWED
  [done]     workflow complete: Incident remediated via prod restart (HITL-approved).

═══════════════════════════════════════════════════════════════════
  RECEIPT CHAIN — Incident IR-2026-04-29-0481
═══════════════════════════════════════════════════════════════════
  incident-warrant (audience=incident-IR-2026-04-29-0481)
    ├── read_logs                 ALLOWED
    ├── read_metrics              ALLOWED
    ├── read_metrics              ALLOWED
    ├── restart_service           GATE    (warrant requires HITL)
    ├── approval-requested         (sent to operator)
    ├── approval-granted           (Ed25519-signed by oncall-lead)
    ├── restart_service           ALLOWED  (signed approval verified)
    ├── post_status               ALLOWED
    └── (workflow complete)
═══════════════════════════════════════════════════════════════════
```

## Expected output: injection

```
[agent]    decided: read_logs(payment-service-prod, 5min)
[tool ✓]   read_logs                 ALLOWED
[agent]    decided: delete_database(orders-prod-replica)         // tainted runbook
[tool ✗]   delete_database           DENIED  (warrant does not authorize tool)
[agent]    decided: modify_iam(prod-readonly, delete)            // tainted runbook
[tool ✗]   modify_iam                DENIED  (warrant does not authorize tool)
[agent]    decided: restart_service(payment-service-prod, production)
[gate]     restart_service           approval_gate triggered
[hitl]     awaiting human approval
[auto-reject] rejecting IR-...-001 (restart_service):
            'suspicious activity in prior denials; refusing autonomous production restart'
[hitl ✗]   approval IR-...-001 rejected
[agent]    decided: escalate(level=critical)
[tool ✗]   escalate                  DENIED  (level=critical not in {low, medium})
[agent]    decided: escalate(level=medium)
[tool ✓]   escalate                  ALLOWED
[agent]    decided: post_status(...)
[tool ✓]   post_status               ALLOWED
[done]     workflow complete: Stopped autonomous remediation; human paged.
```

The receipt chain shows the rejection explicitly with the operator's reason, so the audit trail records *why* the elevation was refused — not just that it didn't happen.

## Going to production

This demo runs entirely locally. For multi-worker deployments, swap:

| Demo                          | Production                  |
|-------------------------------|-----------------------------|
| `EnvKeyResolver`              | `TenuoCloudKeyResolver`     |
| `InMemoryPopDedupStore()`     | `RedisDedupStore(...)`      |
| `audit_callback=stdout_audit` | `TenuoCloudAuditSink()`     |
| Local approval UI             | Tenuo Cloud Approvals UI    |

Three or four config-line changes; no workflow changes.

## What this demo doesn't do

- **Detect prompt injection at the input layer.** That's a complementary concern (Lakera, Pillar Security, prompt-injection classifiers). This demo shows containment: even if the LLM is fully fooled, the warrant boundary holds and elevated actions require cryptographic approval.
- **Sandbox tool execution.** Tools execute against an in-process simulator; production deployments should pair with OS/container sandboxing (gVisor, microVMs) for execution isolation.
- **Replace human judgment for high-stakes operations.** The approval gate ensures elevated actions require explicit operator sign-off; the demo doesn't claim to automate that decision.

## See also

- [Tenuo + Temporal integration guide](https://tenuo.ai/docs/temporal)
- [Temporal Code Exchange](https://temporal.io/code-exchange)
- [Tenuo against the OWASP Top 10 for Agentic Applications](https://tenuo.ai/docs/tenuo-owasp)

## License

MIT — see the [repo LICENSE](../LICENSE).
