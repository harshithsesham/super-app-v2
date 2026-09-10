"""`hatch_gws_cli`: the command the gmail skill playbook drives.

    hatch_gws_cli gmail status [--for-command +send]
    hatch_gws_cli gmail accounts
    hatch_gws_cli gmail disconnect
    hatch_gws_cli gmail +triage --query '<gmail query>' --max 50 --format json
    hatch_gws_cli gmail +read --id <message_id> [--headers] --format json
    hatch_gws_cli gmail +send --to a@b.com --subject S --body B [--cc ..]
    hatch_gws_cli gmail +reply --id <message_id> --body B
    hatch_gws_cli gmail +draft --to a@b.com --subject S --body B
    hatch_gws_cli gmail users <resource> <method> --params '<json>' [--json '<json>']
    hatch_gws_cli schema gmail.<method>

Runs inside the agent's shell with HOME set to its home directory; tokens
come from the vault there. Sends and other outward or destructive actions
first ask the daemon for an approval and wait for the user's answer.
Every result is one JSON object on stdout.
"""
from __future__ import annotations
import hashlib, hmac, json, os, pathlib, sys, time, urllib.parse
import httpx
from . import vault
from .gmail import GmailClient, GmailError, configured

HOME = pathlib.Path(os.environ.get("HOME", "~")).expanduser()
PUBLIC_URL = os.environ.get("SUPERAPP_PUBLIC_URL", "http://localhost:18792").rstrip("/")
INTERNAL_URL = os.environ.get("SUPERAPP_INTERNAL_URL", "http://127.0.0.1:18792").rstrip("/")
INTERNAL_TOKEN = os.environ.get("SUPERAPP_INTERNAL_TOKEN", "")
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def out(obj: dict, code: int = 0):
    print(json.dumps(obj, indent=1, default=str))
    sys.exit(code)


def sign_state(action: str) -> str:
    """A link the user can open in a plain browser: it carries the home path
    and an HMAC so the daemon knows whose vault to write."""
    ts = str(int(time.time()))
    msg = f"{action}|{HOME}|{ts}"
    sig = hmac.new(INTERNAL_TOKEN.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.quote(f"{msg}|{sig}", safe="")


def parse_args(argv: list[str]) -> tuple[list[str], dict]:
    pos, opts = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[key] = argv[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            pos.append(a)
            i += 1
    return pos, opts


def client() -> GmailClient:
    tok = vault.load("gmail", HOME)
    if not tok:
        out({"status": "not_connected", "connect_url": f"{PUBLIC_URL}/v1/gmail/connect?state={sign_state('connect')}",
             "message": "Gmail is not connected yet."}, 2)
    return GmailClient(tok, on_refresh=lambda t: vault.store("gmail", t, HOME))


def approve(kind: str, title: str, subtitle: str, details: list[dict]) -> None:
    """Block until the user answers the approval card. Deny ends the command."""
    try:
        r = httpx.post(f"{INTERNAL_URL}/internal/approvals", json={
            "home": str(HOME), "kind": kind, "title": title, "subtitle": subtitle, "details": details},
            headers={"X-Internal-Token": INTERNAL_TOKEN}, timeout=660)
        decision = r.json().get("decision") if r.status_code == 200 else f"error:{r.status_code}"
    except httpx.HTTPError as e:
        decision = f"error:{e}"
    if decision != "allow":
        out({"status": "denied" if decision == "deny" else "not_approved", "decision": decision,
             "message": "The user did not approve this action. Do not retry it without a new request from them."}, 3)


def gmail_status(opts: dict):
    tok = vault.load("gmail", HOME)
    if not tok:
        if not configured():
            out({"status": "not_configured", "message": "The server has no Google OAuth client configured yet."}, 2)
        out({"status": "not_connected",
             "connect_url": f"{PUBLIC_URL}/v1/gmail/connect?state={sign_state('connect')}"}, 0)
    res: dict = {"status": "connected", "email": tok.get("email"), "account_id": "default"}
    cmd = opts.get("for-command")
    if cmd:
        need = None
        if cmd in ("+send", "+reply", "+draft") or ".send" in str(cmd) or "drafts" in str(cmd):
            need = SEND_SCOPE
        elif "modify" in str(cmd) or "labels" in str(cmd) or "trash" in str(cmd) or "settings" in str(cmd):
            need = MODIFY_SCOPE
        if need is None:
            res.update({"scope_key": None, "scope_status": "not_required"})
        else:
            granted = need in (tok.get("scopes") or [])
            res.update({"scope_key": need.rsplit("/", 1)[-1], "scope_status": "granted" if granted else "not_granted"})
            if not granted:
                res["scope_add_url"] = f"{PUBLIC_URL}/v1/gmail/connect?state={sign_state('connect')}"
    out(res)


def triage(opts: dict):
    c = client()
    q = str(opts.get("query", ""))
    n = int(opts.get("max", 50))
    listing = c.list_messages(q, n)
    items = []
    for ref in listing.get("messages", [])[:n]:
        try:
            raw = c.get_message(ref["id"], "metadata", ["From", "To", "Subject", "Date"])
        except GmailError as e:
            if e.status in (403, 404, 410):
                continue
            raise
        items.append(GmailClient.summarize(raw))
    out({"query": q, "count": len(items), "nextPageToken": listing.get("nextPageToken"), "messages": items})


def read(opts: dict):
    c = client()
    raw = c.get_message(str(opts["id"]), "full")
    parsed = GmailClient.parse(raw)
    if not opts.get("headers"):
        parsed.pop("headers", None)
    out(parsed)


def send(opts: dict, reply_to_id: str | None = None):
    c = client()
    to, subject, body, cc = str(opts.get("to", "")), str(opts.get("subject", "")), str(opts.get("body", "")), str(opts.get("cc", ""))
    thread_id, in_reply_to = "", ""
    if reply_to_id:
        orig = GmailClient.parse(c.get_message(reply_to_id, "full"))
        to = to or orig["headers"].get("Reply-To") or orig["from"]
        subject = subject or (orig["subject"] if orig["subject"].lower().startswith("re:") else f"Re: {orig['subject']}")
        thread_id, in_reply_to = orig["threadId"] or "", orig["headers"].get("Message-ID", "")
    if not (to and body):
        out({"status": "error", "message": "--to and --body are required"}, 1)
    if not subject:
        out({"status": "error", "message": "A subject is required. To answer an existing message use "
             "`+reply --id <message_id> --body ...` (subject and thread are carried over); for new mail pass --subject."}, 1)
    approve("gmail_send", f"Send email · to {to}", subject or "(no subject)",
            [{"label": "To", "value": to}] + ([{"label": "Cc", "value": cc}] if cc else [])
            + [{"label": "Subject", "value": subject}, {"label": "Body", "value": body[:1500]}])
    res = c.send(to, subject, body, cc, thread_id, in_reply_to)
    out({"status": "sent", "id": res.get("id"), "threadId": res.get("threadId"), "to": to, "subject": subject})


def draft(opts: dict):
    c = client()
    res = c.draft(str(opts.get("to", "")), str(opts.get("subject", "")), str(opts.get("body", "")), str(opts.get("cc", "")))
    out({"status": "drafted", "draft_id": res.get("id"), "message": res.get("message", {})})


WRITE_METHODS = {"send", "delete", "trash", "untrash", "modify", "batchModify", "batchDelete", "create", "update",
                 "patch", "updateVacation", "updateAutoForwarding", "updateImap", "updatePop", "updateLanguage"}


def raw_call(pos: list[str], opts: dict):
    """users <resource...> <method> --params JSON [--json JSON] -> one Gmail API call."""
    c = client()
    if len(pos) < 3 or pos[0] != "users":
        out({"status": "error", "message": "expected: users <resource> <method>"}, 1)
    resources, method = pos[1:-1], pos[-1]
    params = json.loads(str(opts.get("params", "{}")))
    body = json.loads(str(opts["json"])) if opts.get("json") else None
    params.pop("userId", None)
    path = ""
    for r in resources:
        path += f"/{r}"
        rid = params.pop("id" if r == resources[-1] and method not in ("list", "create", "send", "batchModify", "batchDelete") else f"{r[:-1]}Id", None)
        if rid is None and r != resources[-1]:
            rid = params.pop("messageId" if r == "messages" else "id", None)
        if rid:
            path += f"/{rid}"
    http = "GET"
    if method in ("list", "get", "getProfile", "getVacation", "getImap", "getPop", "getLanguage", "getAutoForwarding"):
        http = "GET"
        if method != "get" and method != "list":
            path += f"/{method[3].lower() + method[4:]}"
    elif method == "delete":
        http = "DELETE"
    elif method in ("update", "patch"):
        http = "PUT" if method == "update" else "PATCH"
    else:
        http = "POST"
        if method not in ("create",):
            path += f"/{method}"
    if method in WRITE_METHODS:
        approve(f"gmail_{method}", f"Gmail · {method} on {'/'.join(resources)}", "The agent wants to make a change in your mailbox.",
                [{"label": "Method", "value": f"users.{'.'.join(resources)}.{method}"},
                 {"label": "Params", "value": json.dumps(params)[:600]},
                 {"label": "Body", "value": json.dumps(body)[:1200] if body else "(none)"}])
    try:
        out(c.api(http, path, params, body))
    except GmailError as e:
        out({"status": "error", "http_status": e.status, "message": str(e)}, 1)


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        out({"usage": __doc__})
    if argv[0] == "schema":
        out({"method": argv[1] if len(argv) > 1 else "", "note": "Pass Gmail API parameters in --params as JSON and a request body in --json. "
             "Resources: messages, threads, labels, drafts, settings. Methods follow the Gmail REST API."})
    if argv[0] != "gmail":
        out({"status": "error", "message": f"unknown service {argv[0]}; only gmail is available"}, 1)
    pos, opts = parse_args(argv[1:])
    if not pos or opts.get("help") or "--help" in argv:
        out({"commands": ["status", "accounts", "disconnect", "+triage", "+read", "+send", "+reply", "+draft",
                          "users <resource> <method>"]})
    cmd = pos[0]
    try:
        if cmd == "status":
            gmail_status(opts)
        elif cmd == "accounts":
            tok = vault.load("gmail", HOME)
            out({"accounts": [{"account_id": "default", "email": tok.get("email")}] if tok else []})
        elif cmd == "disconnect":
            out({"disconnect_url": f"{PUBLIC_URL}/v1/gmail/disconnect?state={sign_state('disconnect')}"})
        elif cmd == "+triage":
            triage(opts)
        elif cmd == "+read":
            read(opts)
        elif cmd == "+send":
            send(opts)
        elif cmd == "+reply":
            send(opts, reply_to_id=str(opts.get("id", "")))
        elif cmd == "+draft":
            draft(opts)
        elif cmd == "users":
            raw_call(pos, opts)
        else:
            out({"status": "error", "message": f"unknown command {cmd}"}, 1)
    except GmailError as e:
        if e.status in (401, 403):
            out({"status": "error", "http_status": e.status, "message": str(e),
                 "hint": "insufficient authentication scopes or an expired connection; run `gmail status --for-command <command>`"}, 1)
        out({"status": "error", "http_status": e.status, "message": str(e)}, 1)


if __name__ == "__main__":
    main()
