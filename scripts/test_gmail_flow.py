"""End-to-end check of the Gmail connector without Google: a fake Gmail API,
a token planted in the vault, then the CLI the skill uses, driven the way
the agent's shell would run it, including an approval-gated send answered
through the daemon's REST API.

    SUPERAPP_API_TOKEN=... SUPERAPP_HOME_ROOT=... python scripts/test_gmail_flow.py

Requires the daemon running on 127.0.0.1:18792 with the same env.
"""
from __future__ import annotations
import base64, json, os, pathlib, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = pathlib.Path(__file__).resolve().parent.parent
DAEMON = "http://127.0.0.1:18792"
TOKEN = os.environ.get("SUPERAPP_API_TOKEN", "dev-token-local")
HOME_ROOT = pathlib.Path(os.environ.get("SUPERAPP_HOME_ROOT", "~/.superapp/users")).expanduser()
HOME = HOME_ROOT / "default"

MSG = {"id": "m1", "threadId": "t1", "labelIds": ["INBOX", "UNREAD"], "internalDate": str(int(time.time() * 1000)),
       "snippet": "Are we still on for Friday?",
       "payload": {"headers": [{"name": "From", "value": "Jane Doe <jane@example.com>"}, {"name": "To", "value": "me@example.com"},
                               {"name": "Subject", "value": "Friday plans"}, {"name": "Date", "value": "Wed, 10 Sep 2026 09:00:00 -0500"},
                               {"name": "Message-ID", "value": "<abc@example.com>"}],
                   "mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"Are we still on for Friday?\nJane").decode()}}}
SENT: list[dict] = []


class FakeGmail(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p.endswith("/profile"): return self._json({"emailAddress": "me@example.com", "historyId": "1"})
        if p.endswith("/messages"): return self._json({"messages": [{"id": "m1", "threadId": "t1"}], "resultSizeEstimate": 1})
        if p.endswith("/messages/m1"): return self._json(MSG)
        return self._json({"error": {"message": "not found"}}, 404)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/messages/send"):
            SENT.append(body); return self._json({"id": "sent1", "threadId": body.get("threadId", "t2")})
        return self._json({"error": {"message": "unsupported"}}, 400)


def api(path, method="GET", body=None):
    req = urllib.request.Request(DAEMON + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def cli(*args, env_extra=None):
    env = dict(os.environ, HOME=str(HOME), PATH=str(REPO / "bin") + os.pathsep + os.environ["PATH"])
    env.update(env_extra or {})
    p = subprocess.run(["hatch_gws_cli", *args], capture_output=True, text=True, env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout, "err": p.stderr}


def main():
    srv = HTTPServer(("127.0.0.1", 0), FakeGmail); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake = {"SUPERAPP_GMAIL_API_BASE": f"http://127.0.0.1:{port}"}
    # make sure the room exists so the daemon can map home -> agent
    api("/v1/me")
    internal = api("/v1/me")  # noqa: F841
    # the CLI needs the daemon's internal token; the daemon exposes it only to shells it spawns,
    # so for this test we read it from the running process's environment file the daemon writes.
    tok = os.environ.get("SUPERAPP_INTERNAL_TOKEN")
    if not tok:
        print("SUPERAPP_INTERNAL_TOKEN must match the daemon (start the daemon with it set)"); sys.exit(2)

    print("1. status before connect:", cli("gmail", "status", env_extra=fake))
    from superapp.connectors import vault
    vault.store("gmail", {"access_token": "fake", "refresh_token": "", "expiry_ts": time.time() + 3600,
                          "email": "me@example.com", "scopes": ["https://www.googleapis.com/auth/gmail.send"]}, HOME)
    print("2. status after connect:", cli("gmail", "status", "--for-command", "+send", env_extra=fake)[1])
    print("3. connectors via REST:", api("/v1/connectors"))
    code, tri = cli("gmail", "+triage", "--query", "from:jane", "--max", "5", "--format", "json", env_extra=fake)
    print("4. triage:", code, tri["count"], tri["messages"][0]["subject"])
    code, rd = cli("gmail", "+read", "--id", "m1", "--format", "json", env_extra=fake)
    print("5. read:", code, rd["from"], "|", rd["body"][:40])

    # 6. send: the CLI blocks on an approval; answer it through the app's REST endpoint.
    result = {}
    def run_send():
        result["send"] = cli("gmail", "+reply", "--id", "m1", "--body", "Yes, see you Friday!", env_extra=fake)
    t = threading.Thread(target=run_send); t.start()
    pending = []
    for _ in range(50):
        pending = api("/v1/approvals")["approvals"]
        if pending: break
        time.sleep(0.2)
    print("6a. approval card:", pending[0]["title"], "|", [d["label"] for d in pending[0]["details"]])
    api(f"/v1/approvals/{pending[0]['id']}", "POST", {"decision": "deny"})
    t.join(30)
    print("6b. denied ->", result["send"][0], result["send"][1].get("status"), "| sent:", len(SENT))

    t = threading.Thread(target=run_send); t.start()
    for _ in range(50):
        pending = api("/v1/approvals")["approvals"]
        if pending: break
        time.sleep(0.2)
    api(f"/v1/approvals/{pending[0]['id']}", "POST", {"decision": "allow"})
    t.join(30)
    print("6c. allowed ->", result["send"][0], result["send"][1].get("status"), "| sent:", len(SENT),
          "| threadId:", SENT[-1].get("threadId"))
    vault.delete("gmail", HOME)
    print("7. cleanup: token removed;", api("/v1/connectors")["connectors"][0]["status"])


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    main()
