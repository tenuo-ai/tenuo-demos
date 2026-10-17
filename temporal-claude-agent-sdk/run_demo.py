"""Run the four cases through a real Temporal Worker; scripted or live Claude."""

import argparse
import asyncio
import json
import shutil
import tempfile
import uuid

from policy import PREFIX, task_warrant
from tenuo import SigningKey
from tenuo.temporal import tenuo_headers
from tools import Shop
from worker import make_worker
from workflow import RefundWorkflow

from temporalio.claude_agent_sdk import ClaudeAgentSdkRunner
from temporalio.claude_agent_sdk.testing import Final, ScriptedClaude, ToolCall
from temporalio.client import Client

CASES = [
    ("get_order", {"order_id": "order-123"}),
    ("issue_refund", {"order_id": "order-123", "amount": 25}),
    ("issue_refund", {"order_id": "order-123", "amount": 500}),
    ("delete_order", {"order_id": "order-123"}),
]


def scripted_policy(prompt, history):
    if history:
        return Final(
            json.dumps(
                {"content": history[-1].content, "is_error": history[-1].is_error}
            )
        )
    request = json.loads(prompt)
    return ToolCall(PREFIX + request["name"], request["input"])


async def run(address="localhost:7233", live=False):
    issuer, holder = SigningKey.generate(), SigningKey.generate()
    warrant, shop = task_warrant(issuer, holder), Shop()
    client = await Client.connect(address)
    with tempfile.TemporaryDirectory(prefix="tenuo-claude-") as folder:
        if live:
            runner = ClaudeAgentSdkRunner(
                cwd=folder,
                cli_path=shutil.which("claude"),
                extra_options={
                    "mcp_servers": {"shop": shop.mcp_server()},
                    "setting_sources": [],
                },
            )
        else:
            runner = ScriptedClaude(scripted_policy, engine_tools=shop.engine_tools())
        queue = "tenuo-claude-" + uuid.uuid4().hex
        worker, plugin = make_worker(client, queue, runner, issuer, holder)
        # The Worker has the plugin; this separately connected client needs its
        # client interceptor to inject the task warrant on workflow starts.
        authorized_client = Client(
            client.service_client, interceptors=[plugin.client_interceptor]
        )
        async with worker:
            for name, args in CASES:
                wid = uuid.uuid4().hex
                plugin.client_interceptor.set_headers_for_workflow(
                    wid, tenuo_headers(warrant, "task")
                )
                request = json.dumps({"name": name, "input": args})
                if live:
                    request = (
                        "Call exactly this shop tool once, then report its result: "
                        + request
                    )
                result = await authorized_client.execute_workflow(
                    RefundWorkflow.run,
                    request,
                    id=wid,
                    task_queue=queue,
                )
                print(
                    json.dumps({"requested": {"name": name, "input": args}, **result})
                )
        assert shop.refunds == [{"order_id": "order-123", "amount": 25}], shop.refunds
        assert [name for name, _ in shop.invocations] == ["get_order", "issue_refund"]
        print(json.dumps({"invocations": shop.invocations, "refunds": shop.refunds}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument(
        "--live", action="store_true", help="Use Claude SDK and real model credentials"
    )
    options = parser.parse_args()
    asyncio.run(run(options.address, options.live))
