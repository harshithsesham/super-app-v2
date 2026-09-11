"""credentials.* tools: the Secure Store's entry cards. A request creates a card the
user completes on a secure page; the tool returns the card's embed token for the
reply. No tool returns a stored value."""
from __future__ import annotations
import os, urllib.parse
from ..connectors import credstore
from .registry import REGISTRY, ToolError

PLACE = ("Put embed_token in your reply on its own line, copied exactly, then end your reply. Do not wait or poll: "
         "when the user saves the card you will be told, and you can then sign in with the browser worker's fill_credential action.")


def _room_bits(ctx: dict | None):
    agent = (ctx or {}).get("agent")
    if agent is None:
        raise ToolError("no agent context")
    return agent, agent.memory.home


def _check_url(page_url: str) -> str:
    u = str(page_url or "").strip()
    if not u.startswith("https://"):
        raise ToolError("page_url must be an absolute https URL of the exact sign-in page")
    host = credstore.site_of(u)
    own = credstore.site_of(os.environ.get("SUPERAPP_PUBLIC_URL", "https://app.nutrishiksha.com"))
    if host == own or host.endswith("." + own):
        raise ToolError("the app's own pages are not a credential target")
    return u


def _issue(ctx, kind: str, page_url: str, extra: dict) -> dict:
    agent, home = _room_bits(ctx)
    req = credstore.new_request(home, kind, page_url, extra)
    if req.get("already_sent"):
        return {"status": "already_sent", "request_id": req["id"], "embed_token": req["embed_token"],
                "note": "A card for this site is already in front of the user this turn; point them at it."}
    agent.on_event("credential_request", {"agent": agent.id, "request": req})
    out = {"status": "requested", "request_id": req["id"], "site": req["site"], "embed_token": req["embed_token"], "note": PLACE}
    if kind == "api_key":
        out["capture_link"] = req["embed_token"]
    return out


@REGISTRY.register("credentials.list")
def list_(domain: str | None = None, _ctx: dict | None = None):
    _, home = _room_bits(_ctx)
    return {"logins": credstore.list_entries(home, domain), "note": "Metadata only: values stay in the Secure Store."}


@REGISTRY.register("credentials.request_login")
def request_login(page_url: str, username_hint: str | None = None, _ctx: dict | None = None):
    return _issue(_ctx, "login", _check_url(page_url), {"username_hint": username_hint or ""})


@REGISTRY.register("credentials.request_new_password")
def request_new_password(page_url: str, username_hint: str | None = None, _ctx: dict | None = None):
    return _issue(_ctx, "new_password", _check_url(page_url), {"username_hint": username_hint or ""})


@REGISTRY.register("credentials.request_api_access")
def request_api_access(_ctx: dict | None = None, **kw):
    scheme = str(kw.get("auth_scheme", "api_key"))
    if scheme not in ("api_key", "oauth2_code"):
        raise ToolError(f"auth scheme {scheme} is not supported here; api_key and oauth2_code are")
    hosts = [str(h) for h in (kw.get("api_hosts") or []) if h]
    if not hosts:
        raise ToolError("api_hosts is required")
    provider = str(kw.get("provider") or kw.get("provider_name") or kw.get("service") or hosts[0])
    page = "https://" + hosts[0]
    return _issue(_ctx, "api_key", page, {"provider": provider, "api_hosts": hosts, "auth_scheme": scheme,
                                          "fields": [str(f) for f in (kw.get("fields") or kw.get("field_names") or ["api_key"])]})
