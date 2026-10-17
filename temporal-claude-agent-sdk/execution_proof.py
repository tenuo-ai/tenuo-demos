"""Optional Worker-held identity mode: fresh proof at each Activity ingress.

Unlike adapter.py's schedule-signed mode, this trusts Temporal's authenticated
task delivery and the Worker as the holder. It is not a stale-proof refresher.
Claude never receives the holder key, issuer key, or an authority-update tool.
"""

import base64
import copy
import time

from adapter import ACTIVITIES, CallActivityInterceptor, CallWorkerInterceptor
from policy import resolve_call
from tenuo.temporal._constants import TENUO_POP_HEADER
from tenuo.temporal._headers import (
    _extract_key_id_from_headers,
    _extract_warrant_from_headers,
)
from tenuo.temporal._interceptors import _TenuoWorkflowInboundInterceptor
from tenuo.temporal.exceptions import (
    TenuoContextError,
    _build_non_retryable_application_error,
)

from temporalio import activity, workflow
from temporalio.api.common.v1 import Payload
from temporalio.worker import WorkflowOutboundInterceptor


class ExecutionHeaders(WorkflowOutboundInterceptor):
    def start_activity(self, inp):
        if inp.activity in ACTIVITIES:
            inp = copy.copy(inp)
            # Only already-issued public warrant bytes are Workflow state.
            headers = workflow.instance().authority_headers
            inp.headers = {
                **inp.headers,
                **{k: Payload(data=v) for k, v in headers.items()},
            }
        return self.next.start_activity(inp)


class ExecutionProof(CallActivityInterceptor):
    async def execute_activity(self, inp):
        info = activity.info()
        if info.activity_type not in ACTIVITIES:
            return await super().execute_activity(inp)
        try:
            raw = {key: value.data for key, value in inp.headers.items()}
            # Never launder an existing, potentially invalid, caller proof.
            if TENUO_POP_HEADER in raw:
                raise TenuoContextError(
                    "execution-proof mode does not accept caller proofs"
                )
            warrant = _extract_warrant_from_headers(raw)
            if warrant is None or warrant.session_id != info.workflow_id:
                raise TenuoContextError("warrant belongs to a different workflow")
            key_id = _extract_key_id_from_headers(raw)
            if key_id != "task":
                raise TenuoContextError("unexpected holder key reference")
            if warrant.is_expired():
                raise TenuoContextError(
                    "task warrant has expired; controller renewal required"
                )
            # Validate issuer, expiry and root chain before using the holder key.
            self._authorizer.verify(warrant)
            name, arguments = resolve_call(info.activity_type, inp.args)
            signer = self._config.key_resolver.resolve_sync(key_id)
            proof = warrant.sign(signer, name, arguments, int(time.time()))
            inp = copy.copy(inp)
            inp.headers = {
                **inp.headers,
                TENUO_POP_HEADER: Payload(data=base64.b64encode(bytes(proof))),
            }
        except Exception as exc:
            raise _build_non_retryable_application_error(exc) from exc
        # The unchanged plugin verifies the fresh proof and exact constraints,
        # emits its audit decision, and applies its existing replay protection.
        return await super().execute_activity(inp)


class ExecutionWorkerInterceptor(CallWorkerInterceptor):
    def workflow_interceptor_class(self, input):
        config = self._config

        class Inbound(_TenuoWorkflowInboundInterceptor):
            _config = config

            def init(self, outbound):
                self.next.init(ExecutionHeaders(outbound))

        return Inbound

    def intercept_activity(self, next_interceptor):
        return ExecutionProof(next_interceptor, self._config, self._version)
