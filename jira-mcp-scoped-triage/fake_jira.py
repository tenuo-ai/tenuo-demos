"""A stand-in for a Jira Server REST API. Logs every request to $JIRA_LOG and answers with plausible JSON."""
import json, os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = os.environ["JIRA_LOG"]
TRANSITIONS = {"21": "In Progress", "31": "Done", "41": "Won't Do"}

def issue(key):
    return {"id": "10001", "key": key, "self": f"http://x/rest/api/2/issue/{key}",
            "fields": {"summary": "s", "status": {"name": "Open"}, "issuetype": {"name": "Task"},
                       "project": {"key": key.split("-")[0], "name": "p"}, "comment": {"comments": []},
                       "created": "2026-01-01T00:00:00.000+0000", "updated": "2026-01-01T00:00:00.000+0000"}}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        with open(LOG, "a") as f:
            f.write(f"{self.command} {self.path.split('?')[0]} {body}\n")
        p = self.path.split("?")[0]
        if m := re.fullmatch(r"/rest/api/2/issue/([A-Z]+-\d+)", p):
            out, code = (issue(m[1]), 200) if self.command == "GET" else ({}, 204)
        elif re.fullmatch(r"/rest/api/2/issue/[A-Z]+-\d+/comment", p):
            out, code = {"id": "1", "body": "b", "created": "2026-01-01T00:00:00.000+0000", "author": {"displayName": "a"}}, 201
        elif re.fullmatch(r"/rest/api/2/issue/[A-Z]+-\d+/transitions", p):
            out, code = ({"transitions": [{"id": i, "name": n, "to": {"name": n}} for i, n in TRANSITIONS.items()]}, 200) if self.command == "GET" else ({}, 204)
        elif p == "/rest/api/2/issue":
            out, code = {"id": "10002", "key": "HR-2"}, 201
        elif p.startswith("/rest/api/2/field"):
            out, code = [], 200
        elif p.startswith("/rest/api/2/myself"):
            out, code = {"name": "bot", "displayName": "bot", "accountId": "1"}, 200
        else:
            out, code = {}, 200
        data = json.dumps(out).encode() if code != 204 else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_DELETE = _go

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
