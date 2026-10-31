# Enforcement and refusal semantics

## Versions

- Plugin: draft [temporalio/ai-integrations#33](https://github.com/temporalio/ai-integrations/pull/33),
  installed from git at `4f791d03c2a03a80b109939d8425ec34e1989783` (see `requirements.txt`).
- Tenuo 0.3.5, Temporal SDK 1.34.0, claude-agent-sdk 0.2.153 and its bundled Claude Code.
- The model is the plugin's deterministic local Messages API stand-in from the same
  commit; no hosted model credentials are needed. `run_e2e.sh` runs everything.

## Enforcement boundary

In the pinned upstream `python/claude_agent_sdk/src/temporalio/claude_agent_sdk/`:

- `_models.ToolStepInput.call` is `DeferredCall(id, name, input, kind)`.
- `_activity.make_tool_step_activity` defines `run_claude_tool_step(step)`.
- Its body calls `runner.run_tool_step(step, activity.info().attempt)`.
- `_runner.ClaudeAgentSdkRunner.run_tool_step` releases a matching warm call or
  runs the exact recorded call in Claude Code. It must never be reached on denial.

The example's `CallWorkerInterceptor`, a subclass of Tenuo's existing Worker
interceptor, installs an Activity adapter. Its local resolver is selected
by Activity type and reads the original decoded argument, then existing Tenuo
logic verifies the warrant chain, holder PoP and argument constraints. Only
after authorization and deduplication does it call the next interceptor/body.

The example maps `run_claude_tool_step` →
`step.call.name.removeprefix("mcp__shop__")`, `step.call.input`. The same mapping
is used for outbound proof signing. Neither a static authorization for the
dispatcher nor a constraint on the envelope itself would enforce `amount`.
The adapter creates a per-call config using the existing static `tool_mappings`
option and supplies the extracted arguments to the existing inbound interceptor.
Shared Worker config is never mutated. Its outbound interceptor signs the same
logical call with `Warrant.sign`. This small amount of bridge code is contained
in `adapter.py`; it depends on private APIs in the pinned release. There is no
new core extension point or released-plugin modification.

The step's session/checkpoint/conversation control replay, while the call name
and every logical tool argument determine authorization. In this shop, identity
and amount are entirely in the arguments. Tools whose authority depends on a
workspace, account, or other ambient state must include that context in their
authorization mapping too.

## Exact current denial path

```text
Tenuo inbound authorization fails (no next/body dispatch)
  → ApplicationError(non_retryable=True)
      type="constraint_violation"    (refund 500)
      type="tool_not_authorized"     (delete_order)
  → Temporal failure converter / ActivityError.cause
  → DurableClaudeAgent._execute_tool catches ActivityError
  → _failed_step does not recognize either type as ToolCallNotRun
  → tool_calls status="interrupted"
  → ToolOutcome(is_error=True, content=<below>)
  → next segment injects this outcome into Claude's conversation
```

The exact content produced by the unchanged classifier in the boundary tests:

```text
This call was interrupted (its step failed), so it may have run, in full or in part. Check its effects before you run it again.
```

The boundary tests serialize and restore the failure before calling the real
classifier. Actual injection into the real engine's model request is also verified
by the passing SDK test. In both denied boundary cases, the Activity-body
counter is zero, the implementation invocation list is empty, and no refund
exists. A forced attempt 2 is denied again. The existing failure is
non-retryable, and #33's `_may_try_again` returns false.

## What already works, and the smallest remaining gap

There is already a vendor-neutral public wire signal: an `ApplicationError` with
type `ToolCallNotRun`. An interceptor that knows it refused before dispatch can
raise that type with `non_retryable=True`. It does **not** need the Activity
body's retry enrichment to stop: absent `{"try_again": true}`, `_may_try_again`
returns false. A test proves this existing signal yields `status="not run"`.
So no new pre-execution hook is required just to communicate non-execution.

However, that signal currently produces:

```text
This call did not run: its step failed before the call could start. You can call it again.
```

That describes a setup failure, not a terminal policy refusal. The default
Tenuo plugin also preserves its own error codes, so it does not emit the Claude
integration's signal automatically. A composition adapter must deliberately
translate a proven pre-dispatch denial; catching arbitrary tool errors after
dispatch and relabeling them is unsafe.

We have proposed a small, vendor-neutral fix upstream: an `ApplicationError` type
`TOOL_CALL_REFUSED = "ToolCallRefused"` that trusted Worker middleware raises only
before entering the tool. The plugin records `status="refused"` for a Claude Code
tool step or a durable tool alike, never retries it (it adds the type to every tool
retry policy itself), and tells Claude:

```text
This call was refused by policy before it ran. The same call will be refused again unless its authorization changes.
```

The policy's own message stays in Temporal. No callback, policy SDK, warrant or
vendor import is involved, and Worker loss, timeouts, interruptions, ordinary errors
and the existing retryable `ToolCallNotRun` behavior are unchanged. It is a trusted
Worker contract, not a way to infer that an arbitrary error means nothing happened.
When it lands, this example's adapter will translate a proven pre-dispatch Tenuo
denial into that type.

## Authority lifecycle

The lifecycle keeps the released plugin's model: proofs are signed at scheduling
time in the Workflow and verified at the Activity Worker. Issued public warrant
headers are Workflow state, Temporal Updates carry approval and the controller's
replacement, and no issuing key enters Workflow code or history. Each agent run
is signed under the authority current at its start through the plugin's
per-dispatch warrant override (`warrant_scope` in `adapter.py`). Tests cover
approval-only denial, replacement, old-warrant denial, resource scope, expiry,
untrusted self-issuance, stale proofs and a Worker restart after replacement. See
[LIFECYCLE.md](LIFECYCLE.md) for transport options and proof windows.
