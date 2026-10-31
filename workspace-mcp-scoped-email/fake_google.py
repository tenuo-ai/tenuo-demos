"""Offline stand-in for the Gmail API, so the demo runs without Google credentials.

Swaps Workspace MCP's service factory for a fake that records every send.
Everything above it (the MCP server, its middleware, the real tool code) runs
unchanged.
"""

import base64
import email

import auth.service_decorator as service_decorator

sent: list[dict] = []


class _Request:
    def __init__(self, result, on_execute=None):
        self._result = result
        self._on_execute = on_execute

    def execute(self, **kwargs):
        if self._on_execute:
            self._on_execute()
        return self._result


class _Http:
    http = None

    def close(self):
        pass


class FakeGmail:
    _http = _Http()

    def users(self):
        return self

    def settings(self):
        return self

    def sendAs(self):
        return self

    def messages(self):
        return self

    def threads(self):
        return self

    def get(self, **kwargs):
        return _Request({"id": "thread-4471", "messages": []})

    def list(self, **kwargs):
        return _Request({"sendAs": [{"sendAsEmail": "me@acme.com", "isPrimary": True, "signature": ""}]})

    def send(self, userId, body):
        return _Request({"id": f"msg-{len(sent) + 1}", "threadId": "thread-4471"}, lambda: sent.append(_decode(body)))

    def close(self):
        pass


def _decode(body: dict) -> dict:
    """Recipients and subject of the MIME message Workspace MCP built."""
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
    return {k: msg[k] for k in ("To", "Cc", "Bcc", "Subject") if msg[k]}


async def _fake_authenticate_service(*args, **kwargs):
    return FakeGmail(), "me@acme.com"


def install() -> None:
    service_decorator._authenticate_service = _fake_authenticate_service
