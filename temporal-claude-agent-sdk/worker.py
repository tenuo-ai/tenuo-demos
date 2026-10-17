"""Compose the unchanged #33 Activity factories with Tenuo's plugin."""

from adapter import PocPlugin
from policy import plugin_config
from workflow import RefundWorkflow

from temporalio.claude_agent_sdk import make_segment_activity, make_tool_step_activity
from temporalio.worker import Worker


def make_worker(client, queue, runner, issuer, holder, *, lifecycle=False, **kwargs):
    from lifecycle_workflow import LifecycleWorkflow

    plugin = PocPlugin(plugin_config(issuer, holder, **kwargs), queue)
    activities = [make_segment_activity(runner), make_tool_step_activity(runner)]
    return Worker(
        client,
        task_queue=queue,
        workflows=[LifecycleWorkflow if lifecycle else RefundWorkflow],
        activities=activities,
        plugins=[plugin],
    ), plugin
