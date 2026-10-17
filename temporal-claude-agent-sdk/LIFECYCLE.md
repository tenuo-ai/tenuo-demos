# Task authority and approval

Temporal controls when work runs and how it survives failure. Tenuo controls what authority the agent has when that work runs.

Human approval may cause new authority to be issued, but approval and authority are separate concepts.

```text
User gives application a task
        |
Trusted application issues warrant
        |
Temporal starts durable workflow
        |
Claude chooses actions
        |
Tenuo enforces current authority
        |
        +-- inside warrant --> execute
        |
        +-- outside warrant --> refuse
                                 |
                                 v
                         Temporal can pause
                         for human approval
                                 |
                                 v
                       controller may issue
                         new authority
```

## Runnable lifecycle

`bash run_e2e.sh` tests the lifecycle with both ScriptedClaude and the real Claude
SDK / bundled Claude Code engine against the upstream local Messages API simulator.
With a running Temporal server and the example environment installed, run:

```bash
python run_lifecycle.py --address localhost:7233 --restart
```

This command simulates a human through an ordinary Temporal Update; no approval UI
is added. Its controller and authorization trace comes from issued warrant IDs,
real Tenuo audit callbacks, Workflow queries, and assertions on implementation
invocations and the refund ledger. The deterministic model chooses the requested
tool calls; no prompt carries the authorization boundary.

1. The trusted controller generates separate issuer and holder keys and mints a
   ten-minute execution warrant with the existing `Warrant.mint_builder()` API.
   As everywhere in Tenuo's Temporal plugin, the warrant is scoped by its holder
   key, TTL and argument constraints; it reaches this Workflow through
   `set_headers_for_workflow(workflow_id, ...)` at start. `Exact("order-123")`
   restricts both tool capabilities to this resource; `Range(min=0, max=100)`
   restricts the refund. The model-segment capability grants no shop side effects.
2. `get_order` and refund 25 run. Refund 250 fails before the implementation.
   #33 still reports the known authorization denial to Claude as interrupted /
   may have run. The controller reconciles the actual Tenuo audit decisions and
   implementation ledger before permitting the demo's recovery path. Do not
   infer non-execution from an arbitrary interrupted outcome.
3. The Workflow waits for `approve_refund`. Approval is recorded durably. A
   second 250 request under the original warrant still fails with zero effects.
4. The controller independently decides to mint a **new root execution warrant**
   with the same holder, exact order, and a limit of 250. It sends
   only already-issued warrant headers through `install_authority`. Increasing
   authority cannot be achieved by attenuating the old 100-limit warrant.
5. The Workflow stores these public headers, then waits for `retry_refund`.
   Each agent run is wrapped in `warrant_scope(...)` with the authority current
   at its start, so the retry's Activities are signed with the replacement.
   The restart scenario stops the Worker here and creates a fresh Worker with no
   Workflow cache. Temporal reconstructs the approval and replacement from
   history; the new Worker handles the retry under the replacement warrant.
   Exactly one 250 refund is recorded. The original warrant still denies 250.

These Updates are trusted controller APIs, never model tools. An Update name or
an approver string is not authentication. The demo dev server has no client ACL;
production must authenticate controller/human access using Temporal credentials
and namespace access policy. Claude has only the shop MCP tools, no issuing tool,
no access to controller Updates, and no issuer or holder private key in its input.

## Warrant transport and Workflow state

| Option | Assessment |
|---|---|
| Workflow input | Safe for issued warrant bytes or references; avoid duplicate payloads. Never put private keys here. |
| Initial headers | Existing Tenuo convention; used here with `tenuo_headers` and a holder key ID. Recorded in history. |
| Workflow state + Update | Used for phase replacement. Input events reconstruct the active public headers deterministically on replay. No minting, clock reads, or secret lookups in Workflow code. |
| Activity headers | Snapshot the active phase warrant for every dispatch; later Updates do not rewrite an already scheduled Activity. |
| External reference | Prefer for larger chains and frequent renewal. Resolve in an Activity or at authenticated Worker ingress, not by network I/O inside Workflow code. Record the authority version for audit. |

Both private keys remain in trusted process memory in this PoC; production Workers
should resolve holder identity from the existing KeyResolver / secret store and
controllers should persist their issuer identity separately. Worker restart tests
reuse those keys; they do not demonstrate production secret-store recovery.
History tests scan the serialized protobuf events for raw, hex, and base64 key
material. This guards against accidental serialization, not a formal information
flow proof. Warrants and exact tool inputs are public authorization material but
may contain sensitive business data; apply the deployment's normal history codec.

The ten-minute TTL starts at minting, not first use. Completion stops this Workflow
from scheduling more work; it does not revoke unexpired cryptographic material.
The previous warrant remains valid for its narrower scope until expiry/revocation.
For immediate invalidation, use Tenuo's existing revocation support. Long approval
waits must trigger a controller renewal before starting a new phase. This demo
fails closed on expiry; it does not implement an automatic renewal service. A wait
past expiry may fail its next model-segment Activity before requesting replacement.

Automatic Continue-As-New is disabled for these bounded demo workflows. A production Workflow must
explicitly carry the active authority version/public headers in new-run inputs
or resolve a safe reference again. Blindly forwarding initial headers would
restore the old warrant. Keep history bounded by changing authority per meaningful
phase, not on every model token or tool attempt. A new warrant does not alter the
authority snapshot of queued Activities or authorize retries of ambiguous effects.

## Signing at scheduling time

Both scenarios use the plugin's own proof model. The Workflow signs each
Activity's proof when it schedules it (`workflow.now()`, inside the sandbox), with
the holder key from the `KeyResolver`, and the Activity Worker verifies the
warrant chain, the proof and the argument constraints before the body runs. The
Worker that verifies never signs, so it cannot authorize a call on its own.

Replacing authority mid-Workflow uses the plugin's per-dispatch warrant override,
the one `tenuo_execute_activity(..., warrant=..., key_id=...)` sets for a single
call. The Claude plugin schedules its Activities itself inside `agent.run()`, so
`adapter.warrant_scope(headers)` sets that same override around a whole agent
run. A run therefore never mixes authorities, and a new warrant applies from the
next run on; Activities already scheduled keep the authority they were signed
with.

Proofs carry the plugin's usual time windows. A first attempt is verified within
about a minute of scheduling (`pop_window_secs=30`, `pop_max_windows=5`), and
retries use the wider `retry_pop_max_windows` (default 40 windows). The approval
and replacement waits here happen between agent runs, with no Activity pending,
so every proof is fresh when it is checked. A deployment where Activities can
wait in a queue for longer than that should follow the plugin's guidance:
size `retry_pop_max_windows` to the retry policy, use `workflow_issue_execution`
or `workflow_grant` per phase, or split long work into child workflows, each with
its own warrant.

## Production evolution

**Simple:** one short-lived warrant per Workflow, renewed by a trusted controller
when its task legitimately continues. This demo replaces it after approval.

**Better:** one warrant per meaningful phase: read-only investigation, resolution
with refund up to the approved amount, then notification-only follow-up. Resolve
or renew near phase execution so waiting does not accidentally grant stale power.

**Future:** a parent task warrant attenuated into narrower subagent, child-Workflow,
or phase warrants. Attenuation only narrows authority; an expansion beyond the
parent still requires a fresh controller decision and an appropriately authorized
issuer. No new delegation system or approval protocol is implemented here.
