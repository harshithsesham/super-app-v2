"""Google sign-in for the app (identity only: openid email profile), ported
from the earlier super-app. A signed-in Google account becomes a user with
its own home directory under SUPERAPP_HOME_ROOT, and a bearer session.

GET /v1/auth/google/start     -> 302 to Google's consent screen
GET /v1/auth/google/callback  -> verify with Google, provision the user, issue a
                                 session, bounce into the app via superapp://signed-in

Sessions are stored hashed in <HOME_ROOT>/.sessions.json. Static tokens from
SUPERAPP_API_TOKEN / SUPERAPP_USER_TOKENS keep working alongside.
"""
from __future__ import annotations
import hashlib, hmac, json, os, pathlib, re, secrets, threading, time, urllib.parse
import httpx

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
_lock = threading.Lock()


def home_root() -> pathlib.Path:
    p = pathlib.Path(os.environ.get("SUPERAPP_HOME_ROOT", "~/.superapp/users")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sessions_path() -> pathlib.Path:
    return home_root() / ".sessions.json"


def _load() -> dict:
    p = _sessions_path()
    try:
        return json.loads(p.read_text()) if p.exists() else {"users": {}, "sessions": {}}
    except json.JSONDecodeError:
        return {"users": {}, "sessions": {}}


def _save(data: dict):
    p = _sessions_path()
    p.write_text(json.dumps(data, indent=1))
    try:
        p.chmod(0o600)
    except OSError:
        pass


def _secret() -> bytes:
    return (os.environ.get("SUPERAPP_INTERNAL_TOKEN") or os.environ.get("SUPERAPP_API_TOKEN") or "dev").encode()


def signin_redirect_uri() -> str:
    return os.environ.get("SUPERAPP_GOOGLE_SIGNIN_REDIRECT_URI") or \
        os.environ.get("SUPERAPP_PUBLIC_URL", "http://localhost:18792").rstrip("/") + "/v1/auth/google/callback"


def configured() -> bool:
    return bool(os.environ.get("SUPERAPP_GOOGLE_CLIENT_ID"))


def make_state() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{hmac.new(_secret(), f'signin:{ts}'.encode(), hashlib.sha256).hexdigest()[:24]}"


def check_state(state: str) -> bool:
    ts, _, _ = state.partition(".")
    if not ts.isdigit() or abs(time.time() - int(ts)) > 600:
        return False
    return hmac.compare_digest(f"{ts}.{hmac.new(_secret(), f'signin:{ts}'.encode(), hashlib.sha256).hexdigest()[:24]}", state)


def start_url() -> str:
    params = urllib.parse.urlencode({
        "client_id": os.environ.get("SUPERAPP_GOOGLE_CLIENT_ID", ""), "redirect_uri": signin_redirect_uri(),
        "response_type": "code", "scope": "openid email profile", "state": make_state(), "prompt": "select_account"})
    return f"{GOOGLE_AUTH}?{params}"


def exchange(code: str) -> dict:
    """Code -> verified Google identity {sub, email, name}."""
    tok = httpx.post(GOOGLE_TOKEN, data={
        "client_id": os.environ.get("SUPERAPP_GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("SUPERAPP_GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": signin_redirect_uri(), "grant_type": "authorization_code", "code": code},
        timeout=30).raise_for_status().json()
    info = httpx.get(GOOGLE_USERINFO, timeout=30, headers={"Authorization": f"Bearer {tok['access_token']}"}).raise_for_status().json()
    if not info.get("email_verified", False):
        raise PermissionError("unverified Google email")
    return {"sub": info["sub"], "email": info["email"].lower(), "name": info.get("name", "")}


def _mint_user_id(users: dict, email: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())[:24] or "user"
    cand, n = base, 1
    while cand in users:
        n += 1
        cand = f"{base}{n}"
    return cand


def complete_signin(identity: dict) -> tuple[str, str, str]:
    """Find-or-create the user for this Google identity; issue a session. Returns (user_id, name, token)."""
    with _lock:
        data = _load()
        users = data["users"]
        uid = next((u for u, rec in users.items() if rec.get("sub") == identity["sub"]), None)
        if uid is None:
            uid = next((u for u, rec in users.items() if rec.get("email") == identity["email"]), None)
        if uid is None:
            links = dict(p.split(":", 1) for p in os.environ.get("SUPERAPP_USER_EMAIL_LINKS", "").split(",") if ":" in p)
            uid = links.get(identity["email"]) or _mint_user_id(users, identity["email"])
        users[uid] = {"sub": identity["sub"], "email": identity["email"], "name": identity["name"] or users.get(uid, {}).get("name", ""),
                      "created_at": users.get(uid, {}).get("created_at", time.time())}
        token = secrets.token_urlsafe(32)
        data["sessions"][hashlib.sha256(token.encode()).hexdigest()] = {"user": uid, "created_at": time.time(), "last_used": time.time()}
        _save(data)
    return uid, users[uid]["name"], token


def resolve_session(token: str) -> str | None:
    data = _load()
    row = data["sessions"].get(hashlib.sha256(token.encode()).hexdigest())
    if not row:
        return None
    return row["user"]


def user_record(uid: str) -> dict:
    return _load()["users"].get(uid, {})


def app_redirect(uid: str, name: str, token: str) -> str:
    return "superapp://signed-in?" + urllib.parse.urlencode({"token": token, "user": uid, "name": name})


def import_data(data: dict) -> dict:
    """Merge users and sessions exported from another daemon (migration into the gateway)."""
    with _lock:
        cur = _load()
        cur["users"].update(data.get("users", {}))
        cur["sessions"].update(data.get("sessions", {}))
        _save(cur)
        return {"users": len(cur["users"]), "sessions": len(cur["sessions"])}
