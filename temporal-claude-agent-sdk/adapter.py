"""PoC-only bridge to the unchanged Tenuo Temporal plugin internals.

Keep these private-API dependencies here. Authorization, chain/PoP verification,
auditing and deduplication remain in Tenuo; no package changes are required.
"""

import base64
import copy
from dataclasses import replace

from policy import SEGMENT_ACTIVITY, TOOL_ACTIVITY, resolve_call
from tenuo.temporal import TenuoClientInterceptor, TenuoWorkerInterceptor
from tenuo.temporal._constants import TENUO_POP_HEADER
from tenuo.temporal._headers import _current_workflow_headers
from tenuo.temporal._interceptors import (
    TenuoActivityInboundInterceptor,
    _TenuoWorkflowInboundInterceptor,
    _TenuoWorkflowOutboundInterceptor,
)
from tenuo.temporal._workflow import current_key_id, current_warrant
from tenuo.temporal.exceptions import (
    TenuoContextError,
    _build_non_retryable_application_error,
)
from tenuo.temporal_plugin import _ensure_tenuo_workflow_runner

from temporalio import activity, workflow
from temporalio.api.common.v1 import Payload
from temporalio.plugin import SimplePlugin

ACTIVITIES = {TOOL_ACTIVITY, SEGMENT_ACTIVITY}


class CallSigningInterceptor(_TenuoWorkflowOutboundInterceptor):
    def start_activity(self, inp):
        if inp.activity not in ACTIVITIES:
            return super().start_activity(inp)
        try:
            name, arguments = resolve_call(inp.activity, inp.args)
            warrant = current_warrant()
            signer = self._config.key_resolver.resolve_sync(current_key_id())
            proof = warrant.sign(
                signer, name, arguments, int(workflow.now().timestamp())
            )
            signed = copy.copy(inp)
            signed.headers = {
                **inp.headers,
                **{
                    key: Payload(data=value)
                    for key, value in _current_workflow_headers().items()
                },
                TENUO_POP_HEADER: Payload(data=base64.b64encode(bytes(proof))),
            }
        except Exception as exc:
            raise _build_non_retryable_application_error(
                TenuoContextError(str(exc))
            ) from exc
        return self._next.start_activity(signed)


class CallWorkerInterceptor(TenuoWorkerInterceptor):
    def workflow_interceptor_class(self, input):
        config = self._config

        class WorkflowInbound(_TenuoWorkflowInboundInterceptor):
            _config = config

            def init(self, outbound):
                self.next.init(CallSigningInterceptor(outbound, self._config))

        return WorkflowInbound

    def intercept_activity(self, next_interceptor):
        return CallActivityInterceptor(next_interceptor, self._config, self._version)


class CallActivityInterceptor(TenuoActivityInboundInterceptor):
    async def execute_activity(self, inp):
        activity_type = activity.info().activity_type
        if activity_type not in ACTIVITIES:
            return await super().execute_activity(inp)
        try:
            name, arguments = resolve_call(activity_type, inp.args)
        except TenuoContextError as exc:
            raise _build_non_retryable_application_error(exc) from exc
        # Never mutate shared config: different logical tools can run concurrently.
        scoped = replace(
            self._config,
            tool_mappings={**self._config.tool_mappings, activity_type: name},
        )

        class LogicalCall(TenuoActivityInboundInterceptor):
            def _extract_arguments(self, input, headers=None):
                return arguments

        return await LogicalCall(self._next, scoped, self._version).execute_activity(
            inp
        )


class PocPlugin(SimplePlugin):
    def __init__(self, config, queue, interceptor=CallWorkerInterceptor):
        self.client_interceptor = TenuoClientInterceptor()
        super().__init__(
            "TenuoClaudePoC",
            interceptors=[
                self.client_interceptor,
                interceptor(config, task_queue=queue),
            ],
            workflow_runner=_ensure_tenuo_workflow_runner,
        )
