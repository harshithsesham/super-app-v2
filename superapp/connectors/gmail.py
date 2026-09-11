"""Gmail over the REST API with httpx: OAuth, token refresh, raw API access,
and the few helpers the skill's shortcut commands need. Ported from the
earlier super-app client; the ingest and triage pipeline was left behind
because this runtime reads mail on demand, per task.

Env: SUPERAPP_GOOGLE_CLIENT_ID, SUPERAPP_GOOGLE_CLIENT_SECRET,
     SUPERAPP_GOOGLE_REDIRECT_URI (the daemon's /v1/gmail/callback),
     SUPERAPP_GMAIL_SCOPE_TIER (read | send | modify, default modify).
"""
from __future__ import annotations
import base64, os, re, time
from email.mime.text import MIMEText
from email.utils import parseaddr
from html import unescape
from typing import Callable
import httpx

GMAIL = os.environ.get("SUPERAPP_GMAIL_API_BASE", "https://gmail.googleapis.com/gmail/v1/users/me")  # override for tests
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES_BY_TIER = {
    "read": ["https://www.googleapis.com/auth/gmail.readonly"],
    "send": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"],
    "modify": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send",
               "https://www.googleapis.com/auth/gmail.modify"],
}
CALENDAR = os.environ.get("SUPERAPP_CALENDAR_API_BASE", "https://www.googleapis.com/calendar/v3")   # override for tests
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
# Which Google services one connect asks consent for. Calendar rides on the same account as Gmail.
SERVICES = [x.strip() for x in os.environ.get("SUPERAPP_GOOGLE_SERVICES", "gmail,calendar").split(",") if x.strip()]
MAX_BODY_CHARS = 12000


def wanted_scopes(tier: str) -> list[str]:
    scopes = list(SCOPES_BY_TIER[tier])
    if "calendar" in SERVICES:
        scopes.append(CALENDAR_SCOPE)
    return scopes


def configured() -> bool:
    return bool(os.environ.get("SUPERAPP_GOOGLE_CLIENT_ID"))


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class GmailError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class GmailClient:
    """token: {access_token, refresh_token, expiry_ts, email?}. on_refresh is
    called with the whole token after a refresh so the caller can re-store it."""

    def __init__(self, token: dict | None = None, on_refresh: Callable[[dict], None] | None = None):
        self.token = token or {}
        self.on_refresh = on_refresh
        self.client_id = os.environ.get("SUPERAPP_GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("SUPERAPP_GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get("SUPERAPP_GOOGLE_REDIRECT_URI", "http://localhost:18792/v1/gmail/callback")
        self.tier = os.environ.get("SUPERAPP_GMAIL_SCOPE_TIER", "modify")

    # ---------------------------------------------------------------- oauth --
    def auth_url(self, state: str) -> str:
        params = httpx.QueryParams({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": " ".join(wanted_scopes(self.tier)), "state": state,
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"})
        return f"{AUTH_URL}?{params}"

    def exchange_code(self, code: str) -> dict:
        data = httpx.post(TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code", "code": code}, timeout=30).raise_for_status().json()
        self.token = {"access_token": data["access_token"], "refresh_token": data.get("refresh_token", ""),
                      "expiry_ts": time.time() + data.get("expires_in", 3600) - 60,
                      "scopes": data.get("scope", "").split()}
        return self.token

    def _access_token(self) -> str:
        if self.token.get("expiry_ts", 0) < time.time() and self.token.get("refresh_token"):
            data = httpx.post(TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "grant_type": "refresh_token", "refresh_token": self.token["refresh_token"]},
                timeout=30).raise_for_status().json()
            self.token["access_token"] = data["access_token"]
            self.token["expiry_ts"] = time.time() + data.get("expires_in", 3600) - 60
            if data.get("refresh_token"):
                self.token["refresh_token"] = data["refresh_token"]
            if self.on_refresh:
                self.on_refresh(dict(self.token))
        return self.token["access_token"]

    # -------------------------------------------------------------- raw api --
    def api(self, method: str, path: str, params: dict | None = None, json: dict | None = None, base: str = GMAIL) -> dict:
        resp = httpx.request(method, f"{base}{path}", params=params or None, json=json, timeout=30,
                             headers={"Authorization": f"Bearer {self._access_token()}"})
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                msg = resp.text
            raise GmailError(resp.status_code, msg)
        return resp.json() if resp.content else {}

    def calendar(self, method: str, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        return self.api(method, path, params, json, base=CALENDAR)

    # ------------------------------------------------------------- helpers --
    def profile(self) -> dict:
        return self.api("GET", "/profile")

    def list_messages(self, q: str = "", max_results: int = 50, label_ids: list[str] | None = None,
                      page_token: str = "") -> dict:
        params: dict = {"maxResults": min(max_results, 500)}
        if q:
            params["q"] = q
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token
        return self.api("GET", "/messages", params)

    def get_message(self, mid: str, fmt: str = "full", metadata_headers: list[str] | None = None) -> dict:
        params: dict = {"format": fmt}
        if metadata_headers:
            params["metadataHeaders"] = metadata_headers
        return self.api("GET", f"/messages/{mid}", params)

    @staticmethod
    def summarize(raw: dict) -> dict:
        """Metadata view for triage lists."""
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        name, addr = parseaddr(headers.get("from", ""))
        ts = int(raw.get("internalDate", 0)) / 1000
        return {"id": raw["id"], "threadId": raw.get("threadId"), "from_name": name or addr, "from": addr,
                "to": headers.get("to", ""), "subject": headers.get("subject", ""), "date": headers.get("date", ""),
                "message_sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None,
                "snippet": raw.get("snippet", ""), "labels": raw.get("labelIds", [])}

    @staticmethod
    def parse(raw: dict) -> dict:
        """Full view: summary plus body text and attachment list."""
        out = GmailClient.summarize(raw)
        payload = raw.get("payload", {})
        out["headers"] = {h["name"]: h["value"] for h in payload.get("headers", [])}

        def walk(part, mime):
            if part.get("mimeType") == mime and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"] + "==").decode(errors="ignore")
            return "".join(walk(p, mime) for p in part.get("parts", []))

        def attachments(part, acc):
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                acc.append({"filename": part["filename"], "mimeType": part.get("mimeType"),
                            "size": part["body"].get("size"), "attachmentId": part["body"]["attachmentId"]})
            for p in part.get("parts", []):
                attachments(p, acc)
            return acc

        body = walk(payload, "text/plain").strip() or html_to_text(walk(payload, "text/html"))
        out["body"] = (body or raw.get("snippet", ""))[:MAX_BODY_CHARS]
        out["attachments"] = attachments(payload, [])
        return out

    def _mime(self, to: str, subject: str, body: str, cc: str = "", in_reply_to: str = "") -> str:
        m = MIMEText(body)
        m["To"] = to
        if cc:
            m["Cc"] = cc
        m["Subject"] = subject
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
            m["References"] = in_reply_to
        return base64.urlsafe_b64encode(m.as_bytes()).decode()

    def send(self, to: str, subject: str, body: str, cc: str = "", thread_id: str = "", in_reply_to: str = "") -> dict:
        payload = {"raw": self._mime(to, subject, body, cc, in_reply_to)}
        if thread_id:
            payload["threadId"] = thread_id
        return self.api("POST", "/messages/send", json=payload)

    def draft(self, to: str, subject: str, body: str, cc: str = "", thread_id: str = "") -> dict:
        msg = {"raw": self._mime(to, subject, body, cc)}
        if thread_id:
            msg["threadId"] = thread_id
        return self.api("POST", "/drafts", json={"message": msg})

    def modify(self, mid: str, add: list[str] | None = None, remove: list[str] | None = None) -> dict:
        return self.api("POST", f"/messages/{mid}/modify", json={"addLabelIds": add or [], "removeLabelIds": remove or []})

    def watch(self, topic: str) -> dict:
        return self.api("POST", "/watch", json={"topicName": topic, "labelIds": ["INBOX"]})
