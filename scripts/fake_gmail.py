"""A stand-in Gmail API for local demos: one inbox message from Jane, and
sends are accepted and recorded. Run it, then start the daemon with
SUPERAPP_GMAIL_API_BASE=http://127.0.0.1:18799 and plant a token:

    python scripts/fake_gmail.py &
    python -c "from superapp.connectors import vault; import time, pathlib; vault.store('gmail', {'access_token':'x','refresh_token':'','expiry_ts':time.time()+9e6,'email':'me@example.com','scopes':['https://www.googleapis.com/auth/gmail.send','https://www.googleapis.com/auth/gmail.modify']}, pathlib.Path('<home>'))"
"""
from __future__ import annotations
import base64, json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18799
MSG = {"id": "m1", "threadId": "t1", "labelIds": ["INBOX", "UNREAD"], "internalDate": str(int(time.time() * 1000)),
       "snippet": "Are we still on for Friday?",
       "payload": {"headers": [{"name": "From", "value": "Jane Doe <jane@example.com>"}, {"name": "To", "value": "me@example.com"},
                               {"name": "Subject", "value": "Friday plans"}, {"name": "Date", "value": "Wed, 10 Sep 2026 09:00:00 -0500"},
                               {"name": "Message-ID", "value": "<abc@example.com>"}],
                   "mimeType": "text/plain",
                   "body": {"data": base64.urlsafe_b64encode(b"Hey! Are we still on for dinner Friday at 7? Let me know.\nJane").decode()}}}
SENT: list[dict] = []


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("fake-gmail %s\n" % (fmt % a))

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.endswith("/profile"): return self._json({"emailAddress": "me@example.com", "historyId": "1"})
        if p.endswith("/messages"): return self._json({"messages": [{"id": "m1", "threadId": "t1"}], "resultSizeEstimate": 1})
        if p.endswith("/messages/m1"): return self._json(MSG)
        if p.endswith("/threads/t1"): return self._json({"id": "t1", "messages": [MSG]})
        if p.endswith("/labels/UNREAD"): return self._json({"id": "UNREAD", "threadsUnread": 1, "messagesUnread": 1})
        return self._json({"error": {"message": "not found"}}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/messages/send"):
            SENT.append(body); sys.stderr.write("fake-gmail SENT %s\n" % json.dumps(body)[:200])
            return self._json({"id": f"sent{len(SENT)}", "threadId": body.get("threadId", "t2")})
        if "/modify" in self.path: return self._json({"id": "m1", "labelIds": ["INBOX"]})
        return self._json({"error": {"message": "unsupported"}}, 400)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
