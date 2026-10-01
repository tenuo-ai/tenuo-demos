import asyncio
import hashlib
import hmac
import json
import logging
import os
import time

from aiohttp import web
from temporalio.service import RPCError, RPCStatusCode
from dotenv import load_dotenv

import tenuo_repair
from shared.config import get_temporal_client

'''Approval webhook receiver (optional: Tenuo warrants with Tenuo Cloud).
When an approver approves or denies a tool call in Tenuo Cloud, Cloud calls this receiver, and it
sends the decision to the waiting workflow as a Signal. Create a webhook in Tenuo Cloud for the
approval.approved, approval.denied and approval.expired events, pointing at this receiver's public
URL, and put its secret in tenuo-cloud.env as TENUO_WEBHOOK_SECRET.
    python run_approval_webhook.py   # listens on :8088/tenuo'''

MAX_SKEW_SECONDS = 300


def verify(body: bytes, signature: str, timestamp: str, secret: str) -> bool:
    """Check Tenuo Cloud's HMAC-SHA256 signature. Today Cloud signs the body and sends
    "sha256=<hex>"; its docs describe signing "{timestamp}.{body}" with an X-Tenuo-Timestamp
    header, so that form is accepted too, with a freshness check."""
    if not signature:
        return False
    if timestamp:
        if abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
            return False
        signed = f"{timestamp}.".encode() + body
    else:
        signed = body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


async def handle(request: web.Request) -> web.Response:
    body = await request.read()
    if not verify(body, request.headers.get("X-Tenuo-Signature", ""),
                  request.headers.get("X-Tenuo-Timestamp", ""), os.environ["TENUO_WEBHOOK_SECRET"]):
        return web.Response(status=401)
    event = json.loads(body)
    if not event.get("type", "").startswith("approval.") or event["type"] == "approval.requested":
        return web.Response(status=204)
    data = event.get("data") or {}
    request_id = data.get("request_id") or data.get("id")

    # Read the request back from Cloud rather than trusting the event body for the signatures.
    from tenuo_cloud import AsyncTenuoCloudClient

    cloud = AsyncTenuoCloudClient(api_key=os.environ["TENUO_API_KEY"])
    try:
        cloud_request = await cloud.get_request(request_id)
    finally:
        await cloud.close()
    decision = tenuo_repair.decision_from_cloud_request(cloud_request)
    workflow_id = (cloud_request.get("metadata") or {}).get("workflow_id")
    if decision and workflow_id:
        client = request.app["temporal"]
        try:
            await client.get_workflow_handle(workflow_id).signal(tenuo_repair.APPROVAL_SIGNAL, decision)
            logging.info("Sent %s for %s to %s", event["type"], request_id, workflow_id)
        except RPCError as e:
            if e.status != RPCStatusCode.NOT_FOUND:
                raise
            # The workflow has already finished (say, the warrant expired). Acknowledge the
            # event so Cloud stops retrying it.
            logging.info("Workflow %s has finished; ignoring %s for %s", workflow_id, event["type"], request_id)
    return web.Response(status=204)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv(tenuo_repair.CLOUD_ENV)
    if not os.environ.get("TENUO_WEBHOOK_SECRET"):
        raise SystemExit("TENUO_WEBHOOK_SECRET is not set (tenuo-cloud.env).")
    app = web.Application()
    app["temporal"] = await get_temporal_client()
    app.router.add_post("/tenuo", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("TENUO_WEBHOOK_PORT", "8088"))).start()
    print("Approval webhook receiver listening on :8088/tenuo")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
