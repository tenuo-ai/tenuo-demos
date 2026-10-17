"""Real PoP + authorizer + #33 Activity/failure handling, without a server.

Only Temporal workflow clock/context/scheduling are supplied by a test double.
The call crosses the real SDK payload and failure converters.
"""

import asyncio
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from adapter import CallSigningInterceptor, CallWorkerInterceptor
from policy import PREFIX, TOOL_ACTIVITY, logical_call, plugin_config, task_warrant
from tenuo import SigningKey
from tenuo.temporal import tenuo_headers
from tenuo.temporal._state import _workflow_headers_store
from tools import Shop

from temporalio.api.failure.v1 import Failure
from temporalio.claude_agent_sdk import (
    DeferredCall,
    ToolStepInput,
    ToolStepRetry,
    make_tool_step_activity,
)
from temporalio.claude_agent_sdk._workflow import _failed_step, _may_try_again
from temporalio.claude_agent_sdk.testing import ScriptedClaude
from temporalio.converter import (
    DataConverter,
    DefaultFailureConverter,
    DefaultPayloadConverter,
)
from temporalio.exceptions import ActivityError, ApplicationError, RetryState
from temporalio.testing import ActivityEnvironment
from temporalio.worker import ExecuteActivityInput

pytestmark = pytest.mark.asyncio


class Boundary:
    def __init__(self):
        self.issuer, self.holder = SigningKey.generate(), SigningKey.generate()
        self.warrant = task_warrant(self.issuer, self.holder)
        self.audit = []
        self.config = plugin_config(
            self.issuer,
            self.holder,
            audit_callback=self.audit.append,
            redact_args_in_logs=False,
        )
        self.shop = Shop()
        self.runner = ScriptedClaude(
            lambda *_: None, engine_tools=self.shop.engine_tools()
        )
        self.body = make_tool_step_activity(self.runner)
        self.body_calls = 0

        async def dispatch(inp):
            self.body_calls += 1
            return await inp.fn(*inp.args)

        self.inbound = CallWorkerInterceptor(self.config).intercept_activity(
            SimpleNamespace(execute_activity=dispatch)
        )

    def sign(self, step):
        run_id = uuid.uuid4().hex
        inp = SimpleNamespace(
            activity=TOOL_ACTIVITY, args=[step], headers={}, summary=None
        )
        scheduled = Mock()
        _workflow_headers_store[run_id] = tenuo_headers(self.warrant, "task")
        try:
            with (
                patch(
                    "temporalio.workflow.info",
                    return_value=SimpleNamespace(run_id=run_id),
                ),
                patch(
                    "temporalio.workflow.now", return_value=datetime.now(timezone.utc)
                ),
            ):
                CallSigningInterceptor(scheduled, self.config).start_activity(inp)
        finally:
            _workflow_headers_store.pop(run_id, None)
        scheduled.start_activity.assert_called_once()
        signed = scheduled.start_activity.call_args.args[0]
        assert signed.args == inp.args and signed.activity == inp.activity
        return signed.headers

    async def invoke(self, step, headers=None, attempt=1, activity_id=None):
        if headers is None:
            headers = self.sign(step)
        # Temporal encodes on the workflow side and decodes on the Worker side.
        converter = DataConverter.default
        decoded = (
            await converter.decode(await converter.encode([step]), [ToolStepInput])
        )[0]
        env = ActivityEnvironment()
        env.info = replace(
            env.info,
            activity_type=TOOL_ACTIVITY,
            attempt=attempt,
            activity_id=activity_id or uuid.uuid4().hex,
        )
        inp = ExecuteActivityInput(
            fn=self.body, args=[decoded], executor=None, headers=headers
        )
        return await env.run(self.inbound.execute_activity, inp)


def step(name, **args):
    return ToolStepInput(
        session_id="task",
        checkpoint="cp",
        retry=ToolStepRetry(maximum_attempts=3),
        call=DeferredCall(
            id=uuid.uuid4().hex, name=PREFIX + name, input=args, kind="engine"
        ),
    )


def wire_failure(exc):
    failure = Failure()
    converter, payload = DefaultFailureConverter(), DefaultPayloadConverter()
    converter.to_failure(exc, payload, failure)
    cause = converter.from_failure(failure, payload)
    err = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type=TOOL_ACTIVITY,
        activity_id="tool-test",
        retry_state=RetryState.NON_RETRYABLE_FAILURE,
    )
    err.__cause__ = cause
    return err


async def test_allowed_read_runs():
    boundary = Boundary()
    out = await boundary.invoke(step("get_order", order_id="order-123"))
    assert not out.is_error and out.content["order_id"] == "order-123"
    assert boundary.shop.invocations == [("get_order", {"order_id": "order-123"})]
    assert boundary.body_calls == 1


async def test_allowed_refund_runs_once():
    boundary = Boundary()
    out = await boundary.invoke(step("issue_refund", order_id="order-123", amount=25))
    assert not out.is_error
    assert boundary.shop.refunds == [{"order_id": "order-123", "amount": 25}]
    assert len(boundary.shop.invocations) == boundary.body_calls == 1


@pytest.mark.parametrize(
    "name,args,expected_type",
    [
        (
            "issue_refund",
            {"order_id": "order-123", "amount": 500},
            "constraint_violation",
        ),
        ("delete_order", {"order_id": "order-123"}, "tool_not_authorized"),
    ],
)
async def test_denial_before_body_and_exact_claude_result(name, args, expected_type):
    boundary = Boundary()
    request = step(name, **args)
    headers = boundary.sign(request)
    # Force a second delivery even though the non-retryable failure stops real
    # Temporal retries. Neither delivery can reach the body or tool.
    for attempt in (1, 2):
        with pytest.raises(ApplicationError) as caught:
            await boundary.invoke(request, headers, attempt=attempt)
        assert caught.value.non_retryable
        assert caught.value.type == expected_type
        err = wire_failure(caught.value)
        assert err.cause.type == expected_type
        assert not _may_try_again(err)
        record = {}
        result = _failed_step(err, record)
        assert record["status"] == "interrupted"
        assert result.is_error
        assert result.content == (
            "This call was interrupted (its step failed), so it may have run, in full or in "
            "part. Check its effects before you run it again."
        )
    assert boundary.body_calls == 0
    assert boundary.shop.invocations == []
    assert boundary.shop.refunds == []


async def test_resolution_matches_exact_request_and_ignores_arg_key_header():
    boundary = Boundary()
    requested = step("issue_refund", order_id="order-123", amount=25)
    assert logical_call([requested]) == ("issue_refund", requested.call.input)
    assert logical_call([asdict(requested)]) == ("issue_refund", requested.call.input)
    headers = boundary.sign(requested)
    from temporalio.api.common.v1 import Payload

    headers["x-tenuo-arg-keys"] = Payload(data=b"attacker-chosen")
    await boundary.invoke(requested, headers)
    event = boundary.audit[-1]
    assert event.tool == "issue_refund"
    assert event.arguments == requested.call.input
    # The authorizer's success also proves both sides used identical PoP input.
    assert boundary.shop.invocations == [("issue_refund", requested.call.input)]


@pytest.mark.parametrize("field,value", [("amount", 500), ("order_id", "other-order")])
async def test_payload_tampering_invalidates_pop(field, value):
    boundary = Boundary()
    request = step("issue_refund", order_id="order-123", amount=25)
    headers = boundary.sign(request)
    request.call.input[field] = value
    with pytest.raises(ApplicationError):
        await boundary.invoke(request, headers)
    assert boundary.body_calls == 0 and boundary.shop.invocations == []


async def test_accepted_attempt_replay_is_blocked_by_existing_plugin_dedup():
    boundary = Boundary()
    request = step("issue_refund", order_id="order-123", amount=25)
    headers = boundary.sign(request)
    await boundary.invoke(request, headers, activity_id="same")
    with pytest.raises(ApplicationError, match="replay"):
        await boundary.invoke(request, headers, activity_id="same")
    assert len(boundary.shop.refunds) == len(boundary.shop.invocations) == 1


async def test_malformed_dispatcher_payload_fails_closed():
    boundary = Boundary()
    request = step("get_order", order_id="order-123")
    headers = boundary.sign(request)
    request.call.kind = "durable"
    with pytest.raises(ApplicationError) as caught:
        await boundary.invoke(request, headers)
    assert caught.value.type == "CONTEXT_MISSING" and caught.value.non_retryable
    assert boundary.body_calls == 0


async def test_existing_generic_not_run_signal_already_works_without_body_enrichment():
    boundary = Boundary()
    with pytest.raises(ApplicationError) as caught:
        await boundary.invoke(step("issue_refund", order_id="order-123", amount=500))
    assert boundary.body_calls == 0
    # An adapter at this proven pre-dispatch boundary could already emit the
    # public #33 signal. No retry decision detail is needed to stop retries.
    signal = ApplicationError(
        "authorization denied", type="ToolCallNotRun", non_retryable=True
    )
    signal.__cause__ = caught.value
    error = wire_failure(signal)
    record = {}
    outcome = _failed_step(error, record)
    assert record["status"] == "not run" and not _may_try_again(error)
    assert outcome.content == (
        "This call did not run: its step failed before the call could start. You can call it again."
    )
    assert boundary.shop.invocations == boundary.shop.refunds == []


async def test_logical_resolver_overrides_static_activity_mapping():
    boundary = Boundary()
    boundary.config.tool_mappings[TOOL_ACTIVITY] = "wrong_static_dispatcher_grant"
    await boundary.invoke(step("get_order", order_id="order-123"))
    assert boundary.audit[-1].tool == "get_order"
    assert boundary.shop.invocations == [("get_order", {"order_id": "order-123"})]


async def test_allowed_name_substitution_cannot_reuse_another_tools_pop():
    boundary = Boundary()
    request = step("get_order", order_id="order-123")
    headers = boundary.sign(request)
    request.call.name = PREFIX + "issue_refund"
    request.call.input["amount"] = 25
    with pytest.raises(ApplicationError):
        await boundary.invoke(request, headers)
    assert boundary.body_calls == 0 and boundary.shop.invocations == []


async def test_concurrent_calls_keep_shared_worker_mapping_unchanged():
    boundary = Boundary()
    original = dict(boundary.config.tool_mappings)
    read, refund = await asyncio.gather(
        boundary.invoke(step("get_order", order_id="order-123")),
        boundary.invoke(step("issue_refund", order_id="order-123", amount=25)),
    )
    assert not read.is_error and not refund.is_error
    assert boundary.config.tool_mappings == original
    assert {event.tool for event in boundary.audit} == {"get_order", "issue_refund"}
    assert boundary.shop.refunds == [{"order_id": "order-123", "amount": 25}]
