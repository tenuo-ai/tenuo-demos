"""Opt-in real Temporal Worker tests. The SDK test uses a local fake model."""

import asyncio
import importlib.util
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from pinned import PLUGIN_COMMIT
from policy import PREFIX, task_warrant
from run_demo import CASES, run
from run_lifecycle import run as run_lifecycle
from tenuo import SigningKey
from tenuo.temporal import tenuo_headers
from tools import Shop
from worker import make_worker
from workflow import RefundWorkflow

from temporalio.claude_agent_sdk import ClaudeAgentSdkRunner
from temporalio.client import Client

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("TEMPORAL_ADDRESS"),
        reason="set TEMPORAL_ADDRESS for real Worker tests",
    ),
]


async def test_scripted_worker_all_four_cases():
    await asyncio.wait_for(run(os.environ["TEMPORAL_ADDRESS"]), 90)


async def test_real_sdk_with_fake_model(tmp_path):
    checkout = os.environ.get("AI_INTEGRATIONS_CHECKOUT")
    if not checkout:
        pytest.skip("set AI_INTEGRATIONS_CHECKOUT to a checkout of the pinned plugin")
    head = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", checkout, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip() == PLUGIN_COMMIT
    # Reuse the exact PR's API simulator; no copied or reimplemented model server.
    helper = (
        Path(checkout) / "python/claude_agent_sdk/tests/helpers/fake_messages_api.py"
    )
    spec = importlib.util.spec_from_file_location("pr33_fake_model", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The upstream simulator selects task requests by MCP server prefix.
    module.PREFIX = PREFIX

    for name, args in CASES:
        shop, observed = Shop(), []
        holder, issuer = SigningKey.generate(), SigningKey.generate()
        ref = []

        def model(body, *, ref=ref, name=name, args=args, observed=observed):
            uses, _, history = module.history_of(body)
            # The first answer emits one exact tool call. The next records what
            # Claude actually receives, then ends the turn.
            if not uses:
                return [ref[0].call(PREFIX + name, args)]
            observed[:] = history
            return [{"type": "text", "text": "Finished"}]

        api = module.FakeMessagesAPI(model)
        ref.append(api)
        api.start()
        folder = tmp_path / uuid.uuid4().hex
        folder.mkdir()
        try:
            runner = ClaudeAgentSdkRunner(
                cwd=str(folder),
                cli_path=os.environ.get("CLAUDE_CLI_PATH"),
                env=module.engine_env(api, str(folder / "config")),
                extra_options={
                    "mcp_servers": {"shop": shop.mcp_server()},
                    "setting_sources": [],
                },
            )
            client = await Client.connect(os.environ["TEMPORAL_ADDRESS"])
            wid = "sdk-" + uuid.uuid4().hex
            worker, plugin = make_worker(client, wid, runner, issuer, holder)
            authorized = Client(
                client.service_client, interceptors=[plugin.client_interceptor]
            )
            plugin.client_interceptor.set_headers_for_workflow(
                wid, tenuo_headers(task_warrant(issuer, holder), "task")
            )
            async with worker:
                result = await asyncio.wait_for(
                    authorized.execute_workflow(
                        RefundWorkflow.run,
                        "Handle this order",
                        id=wid,
                        task_queue=wid,
                    ),
                    120,
                )
                history = await authorized.get_workflow_handle(wid).fetch_history()
            assert len(result["calls"]) == 1
            call = result["calls"][0]
            assert call["name"] == PREFIX + name and call["input"] == args
            assert api.errors == []
            assert len(observed) == 1
            denied = name == "delete_order" or args.get("amount", 0) > 100
            if denied:
                assert shop.invocations == shop.refunds == []
                assert call["status"] == "interrupted"
                assert observed[0].is_error
                assert "so it may have run" in str(observed[0].content)
                failures = [
                    event.activity_task_failed_event_attributes
                    for event in history.events
                    if event.HasField("activity_task_failed_event_attributes")
                ]
                assert len(failures) == 1
                failure = failures[0].failure.application_failure_info
                assert failure.non_retryable
                assert failure.type == (
                    "tool_not_authorized"
                    if name == "delete_order"
                    else "constraint_violation"
                )
            else:
                assert shop.invocations == [(name, args)]
                assert call["status"] == "done" and not observed[0].is_error
                assert shop.refunds == ([args] if name == "issue_refund" else [])
        finally:
            api.stop()


async def test_real_sdk_warrant_lifecycle_with_fake_model(tmp_path):
    checkout = os.environ.get("AI_INTEGRATIONS_CHECKOUT")
    if not checkout:
        pytest.skip("set AI_INTEGRATIONS_CHECKOUT to a checkout of the pinned plugin")
    helper = (
        Path(checkout) / "python/claude_agent_sdk/tests/helpers/fake_messages_api.py"
    )
    spec = importlib.util.spec_from_file_location("pr33_lifecycle_model", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PREFIX = PREFIX
    from run_demo import scripted_policy

    api = module.start_with_policy(scripted_policy)

    def runner_factory(shop):
        folder = tmp_path / uuid.uuid4().hex
        folder.mkdir()
        return ClaudeAgentSdkRunner(
            cwd=str(folder),
            cli_path=os.environ.get("CLAUDE_CLI_PATH"),
            env=module.engine_env(api, str(folder / "config")),
            extra_options={
                "mcp_servers": {"shop": shop.mcp_server()},
                "setting_sources": [],
            },
        )

    try:
        result, shop, audit, *_ = await run_lifecycle(
            os.environ["TEMPORAL_ADDRESS"],
            restart=True,
            runner_factory=runner_factory,
        )
        assert result["phase"] == "complete" and len(result["calls"]) == 5
        assert [e.decision for e in audit if e.tool == "issue_refund"] == [
            "ALLOW",
            "DENY",
            "DENY",
            "ALLOW",
        ]
        assert shop.refunds == [
            {"order_id": "order-123", "amount": 25},
            {"order_id": "order-123", "amount": 250},
        ]
        assert api.errors == []
    finally:
        api.stop()
