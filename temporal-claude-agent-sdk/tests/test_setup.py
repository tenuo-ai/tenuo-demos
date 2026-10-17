"""Validate real SDK configuration and workflow sandbox imports without sockets."""

from unittest.mock import Mock

import pytest
from adapter import CallWorkerInterceptor
from lifecycle_workflow import LifecycleWorkflow
from policy import plugin_config
from tenuo import SigningKey
from tools import Shop
from worker import make_worker
from workflow import RefundWorkflow

from temporalio.claude_agent_sdk import ClaudeAgentSdkRunner, make_tool_step_activity
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)
from temporalio.workflow import _Definition


@pytest.mark.asyncio
async def test_workflow_prepares_in_temporal_sandbox():
    runner = SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "tenuo", "tenuo_core"
        )
    )
    runner.prepare_workflow(_Definition.must_from_class(RefundWorkflow))


def test_real_sdk_runner_accepts_shop_configuration(tmp_path):
    runner = ClaudeAgentSdkRunner(
        cwd=str(tmp_path),
        env={"ANTHROPIC_API_KEY": "sk-ant-fake-not-real"},
        extra_options={
            "mcp_servers": {"shop": Shop().mcp_server()},
            "setting_sources": [],
        },
    )
    body = make_tool_step_activity(runner)
    assert body.__temporal_activity_definition.name == "run_claude_tool_step"


def test_activity_interceptor_initializes_its_downstream():
    issuer, holder = SigningKey.generate(), SigningKey.generate()
    downstream, outbound = Mock(), Mock()
    interceptor = CallWorkerInterceptor(
        plugin_config(issuer, holder)
    ).intercept_activity(downstream)
    interceptor.init(outbound)
    downstream.init.assert_called_once_with(outbound)


def test_approval_cannot_be_overwritten_before_phase_advances():
    instance = LifecycleWorkflow()
    instance.phase = "awaiting approval"
    instance.approve_refund(True)
    with pytest.raises(ValueError):
        instance.approve_refund(False)
    assert instance.approved is True


def test_replacement_cannot_be_overwritten_before_phase_advances():
    instance = LifecycleWorkflow()
    instance.phase, instance.approved = "awaiting authority", True
    original = {"x-tenuo-warrant": b"first issued warrant"}
    instance.install_authority(original)
    with pytest.raises(ValueError):
        instance.install_authority({"x-tenuo-warrant": b"second issued warrant"})
    assert instance.replacement == original


def test_execution_proofs_cannot_enable_a_wider_retry_window():
    issuer, holder = SigningKey.generate(), SigningKey.generate()
    with pytest.raises(ValueError, match="strict retry verification"):
        make_worker(
            Mock(),
            "task",
            Mock(),
            issuer,
            holder,
            lifecycle=True,
            retry_pop_max_windows=40,
        )
