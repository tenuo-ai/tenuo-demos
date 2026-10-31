"""A stand-in for Alpaca's paper trading API. Logs every request to $ALPACA_LOG and answers with plausible JSON."""

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ["ALPACA_LOG"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        path = self.path.split("?")[0]
        with open(LOG, "a") as f:
            f.write(f"{self.command} {self.path} {body}\n")
        if self.command == "POST" and path == "/v2/orders":
            order = json.loads(body or "{}")
            out = {"id": str(uuid.uuid4()), "status": "accepted", **order}
        elif self.command == "DELETE" and path in ("/v2/orders", "/v2/positions"):
            out = []
        elif path == "/v2/account":
            out = {"id": "acct", "status": "ACTIVE", "buying_power": "100000", "cash": "100000"}
        else:
            out = {}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = do_PATCH = _handle


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
