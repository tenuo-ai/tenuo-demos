"""FastAPI HITL approval UI — the live browser surface for the human.

Imported by `run.py` and started in-process via `serve_in_background()`
so the demo runs as a single command. The UI shares the worker's
Temporal client and the on-call lead's signing key directly through
function arguments; nothing flows through `.env` or a separate process.

What the UI shows
-----------------
A pending-approvals page listing every running incident workflow that
has at least one pending approval request. Each request renders as a
card with: workflow ID, requested action, arguments, and Approve /
Reject buttons.

How it integrates with the workflow
-----------------------------------
1. Polls `IncidentResponseWorkflow.pending_approvals` query across all
   running workflows. The query returns each pending entry with the
   canonical `request_hash_b64` — the bytes the operator must sign.
2. On Approve: builds an `ApprovalPayload(request_hash, nonce, ...)`,
   signs with `SignedApproval.create(payload, oncall_keypair)`, sends
   the base64-encoded artifact via the workflow's `submit_approval`
   signal. The workflow attaches it via `set_activity_approvals(...)`,
   the activity inbound's `verify_approvals` runs Ed25519 verification
   + request-hash binding + approver-pubkey check before dispatching.
3. On Reject: signals `submit_approval` with `granted=False`. The
   workflow falls through to the agent's safe path (escalate).

Production substitution
-----------------------
This local UI exists for demo runnability. In real deployments the
operator approves via Tenuo Cloud (managed UI + KMS-held signing key)
or your own approval service. The signal shape and signature format
are identical; only the hosting and key custody change.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from temporalio.client import Client

from tenuo import SigningKey

import workflow as wf


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────


def make_app(client: Client, issuer_key: SigningKey) -> FastAPI:
    """Build a FastAPI app bound to the given Temporal client and
    operator signing key. Both are captured in closure so route
    handlers can sign approvals and signal workflows without touching
    module state or environment variables."""
    state: dict[str, Any] = {"client": client, "issuer_key": issuer_key}
    app = FastAPI(title="Tenuo + Temporal HITL approval UI")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        pending = await _list_pending(state["client"])
        if not pending:
            body = (
                '<p class="empty">No pending approvals. '
                'Waiting for incidents that need a human in the loop&hellip;</p>'
            )
        else:
            body = "\n".join(_render_card(p) for p in pending)
        return _PAGE.format(body=body, count=len(pending))

    @app.post("/approvals/{workflow_id}/{approval_id}/approve")
    async def approve(workflow_id: str, approval_id: str, request: Request):
        """Sign the SignedApproval and signal the workflow."""
        form = await request.form()
        request_hash_b64 = form.get("request_hash_b64")
        action = form.get("action")

        if not (request_hash_b64 and action):
            return RedirectResponse("/?err=missing_fields", status_code=303)

        request_hash = base64.b64decode(request_hash_b64)
        signed_bytes = wf.sign_approval(
            request_hash=request_hash,
            external_id=approval_id,
            operator_keypair=state["issuer_key"],
            ttl_seconds=120,
        )
        signed_b64 = base64.b64encode(signed_bytes).decode()

        handle = state["client"].get_workflow_handle(workflow_id)
        await handle.signal(
            wf.IncidentResponseWorkflow.submit_approval,
            {
                "approval_id": approval_id,
                "granted": True,
                "signed_approval_b64": signed_b64,
            },
        )
        return RedirectResponse(f"/?approved={approval_id}", status_code=303)

    @app.post("/approvals/{workflow_id}/{approval_id}/reject")
    async def reject(
        workflow_id: str,
        approval_id: str,
        reason: str = Form("operator declined"),
    ):
        handle = state["client"].get_workflow_handle(workflow_id)
        await handle.signal(
            wf.IncidentResponseWorkflow.submit_approval,
            {
                "approval_id": approval_id,
                "granted": False,
                "reason": reason,
            },
        )
        return RedirectResponse(f"/?rejected={approval_id}", status_code=303)

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Background server
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def serve_in_background(
    client: Client,
    issuer_key: SigningKey,
    *,
    host: str = "127.0.0.1",
    port: int = 5050,
):
    """Run the approval UI as an asyncio task for the duration of the
    ``async with`` block.

    Yields the ``uvicorn.Server`` so the caller can read addresses if
    needed. On exit, signals graceful shutdown and awaits the serve
    task so uvicorn's lifespan handler unwinds cleanly (avoids the
    ``CancelledError`` traceback that otherwise prints when the parent
    task simply cancels uvicorn mid-receive).
    """
    config = uvicorn.Config(
        make_app(client, issuer_key),
        host=host,
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        yield server
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Pending-approval discovery
# ─────────────────────────────────────────────────────────────────────────────


async def _list_pending(client: Client) -> list[dict[str, Any]]:
    """Find every running IncidentResponseWorkflow with a pending
    approval. Returns flat list with workflow_id stitched in."""
    out: list[dict[str, Any]] = []
    query = (
        "WorkflowType = 'IncidentResponseWorkflow' "
        "AND ExecutionStatus = 'Running'"
    )
    async for execution in client.list_workflows(query=query):
        try:
            handle = client.get_workflow_handle(execution.id)
            items = await handle.query(wf.IncidentResponseWorkflow.pending_approvals)
        except Exception:
            continue
        for item in items:
            out.append({**item, "workflow_id": execution.id})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def _render_card(pending: dict[str, Any]) -> str:
    args_summary = ", ".join(f"<b>{k}</b>=<code>{v}</code>" for k, v in pending["args"].items())
    return f"""
    <div class="card">
      <div class="meta">
        <span class="incident">Incident: <code>{pending['workflow_id']}</code></span>
        <span class="approval-id">Approval: <code>{pending['approval_id']}</code></span>
      </div>
      <div class="action">
        <span class="tool">{pending['action']}</span>(
          {args_summary}
        )
      </div>
      <p class="rationale">
        Operator approval will mint a SignedApproval bound to
        request_hash <code>{pending['request_hash_b64'][:12]}…</code>,
        signed by your key. The activity inbound verifies the signature
        against the warrant's <code>required_approvers</code> before
        dispatching the action.
      </p>
      <div class="actions">
        <form method="POST"
              action="/approvals/{pending['workflow_id']}/{pending['approval_id']}/approve"
              style="display:inline">
          <input type="hidden" name="request_hash_b64" value="{pending['request_hash_b64']}" />
          <input type="hidden" name="action" value="{pending['action']}" />
          <button class="approve" type="submit">Sign and approve</button>
        </form>
        <form method="POST"
              action="/approvals/{pending['workflow_id']}/{pending['approval_id']}/reject"
              style="display:inline">
          <button class="reject" type="submit">Reject</button>
        </form>
      </div>
    </div>
    """


_PAGE = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Tenuo + Temporal HITL approval</title>
  <meta http-equiv="refresh" content="3" />
  <style>
    :root {{ --bg: #f7f8fa; --fg: #1a1c20; --muted: #6b7280;
             --accent: #1f2937; --green: #16a34a; --red: #dc2626; }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      background: var(--bg); color: var(--fg);
      max-width: 760px; margin: 2em auto; padding: 0 1.2em;
    }}
    h1 {{ font-weight: 600; letter-spacing: -0.01em; }}
    .count {{ color: var(--muted); font-weight: 400; font-size: 0.85em; }}
    .card {{
      background: white; border: 1px solid #e5e7eb;
      border-radius: 8px; padding: 1.4em 1.6em; margin: 1em 0;
      box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }}
    .meta {{ display: flex; justify-content: space-between;
             color: var(--muted); font-size: 0.85em; margin-bottom: 0.5em; }}
    .action {{ font-size: 0.95em; font-weight: 500; margin: 0.5em 0;
               line-height: 1.5; overflow-wrap: anywhere; }}
    .action .tool {{ color: var(--accent); font-family: ui-monospace, monospace;
                     font-size: 1.05em; }}
    .action code {{ font-size: 0.9em; }}
    .rationale {{ color: var(--muted); font-size: 0.85em; line-height: 1.5; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
            background: #f3f4f6; padding: 0.1em 0.35em; border-radius: 3px;
            font-size: 0.9em; }}
    .actions {{ margin-top: 1.2em; display: flex; gap: 0.6em; }}
    button {{
      padding: 0.7em 1.5em; border: 0; border-radius: 5px; cursor: pointer;
      font-size: 0.95em; font-weight: 500;
    }}
    button.approve {{ background: var(--green); color: white; }}
    button.approve:hover {{ background: #15803d; }}
    button.reject  {{ background: var(--red);   color: white; }}
    button.reject:hover  {{ background: #b91c1c; }}
    .empty {{ color: var(--muted); font-style: italic; }}
  </style>
</head>
<body>
  <h1>Pending approvals
    <span class="count">({count})</span>
  </h1>
  {body}
</body>
</html>
"""
