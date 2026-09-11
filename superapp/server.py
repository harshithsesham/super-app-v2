"""HTTP + WebSocket server: the daemon the mobile and web clients talk to.

One Agent per user, kept warm in memory, with its transcript persisted under
the user's home. Turns run on a worker thread; text deltas and runtime events
are fanned out to every connected socket for that user as JSON frames.

Auth: bearer tokens from SUPERAPP_USER_TOKENS ("alice:tok1,bob:tok2") or the
single SUPERAPP_API_TOKEN (user "default"). Google sign-in comes later.

    ./.venv/bin/uvicorn superapp.server:app --host 0.0.0.0 --port 18792

WebSocket protocol at /v1/ws?token=...:
  client -> {"type": "message", "text": "..."}
  client -> {"type": "stop"}
  server -> {"type": "turn_start"} | {"type": "text_delta", "text"} | {"type": "event", "kind", "data"}
            | {"type": "turn_end", "text"} | {"type": "history", "messages": [...]} | {"type": "error", "message"}
"""
from __future__ import annotations
import asyncio, hashlib, hmac, json, os, pathlib, secrets, threading, time, urllib.parse
from typing import Any
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import CONFIG
from .memory.files import HomeMemory
from .prompts import skills_catalog
from .tools import local, memory_tools  # noqa: F401  registers handlers
from .agent import subagents  # noqa: F401
from .browser import worker as browser_worker, web as browser_web  # noqa: F401
from .agent.loop import Agent
from .agent import subagents as subagent_mod
from . import auth, db, hub, voice
from .approvals import Approval, ApprovalStore
from .scheduler import tools as scheduler_tools  # noqa: F401  registers cron.*, hooks.*, muse.nothing_to_do
from .scheduler.engine import Engine
from .connectors import vault
from .connectors.gmail import GmailClient, configured as gmail_configured

app = FastAPI(title="superapp daemon", version="0.1.0")
_bearer = HTTPBearer(auto_error=False)

# Connector CLIs the agent runs in its shell reach back here. The token is
# per process and reaches the CLIs through the shell environment only.
os.environ.setdefault("SUPERAPP_INTERNAL_TOKEN", secrets.token_urlsafe(24))
os.environ.setdefault("SUPERAPP_INTERNAL_URL", f"http://127.0.0.1:{os.environ.get('SUPERAPP_PORT', '18792')}")
os.environ.setdefault("SUPERAPP_PUBLIC_URL", os.environ["SUPERAPP_INTERNAL_URL"].replace("127.0.0.1", "localhost"))
INTERNAL_TOKEN = os.environ["SUPERAPP_INTERNAL_TOKEN"]
PUBLIC_URL = os.environ["SUPERAPP_PUBLIC_URL"].rstrip("/")

# Cell mode: this process serves exactly one user (one Firecracker machine per
# user, Muse's runtime cell). The gateway authenticates the person and forwards
# with the cell token. With SUPERAPP_IDLE_EXIT_SECS set, the daemon exits 0 once
# nothing is happening and no scheduled work is near, so the machine stops; the
# gateway starts it again on the next request or before the next due job.
CELL_USER = os.environ.get("SUPERAPP_CELL_USER") or None
CELL_TOKEN = os.environ.get("SUPERAPP_CELL_TOKEN") or None
IDLE_EXIT_SECS = int(os.environ.get("SUPERAPP_IDLE_EXIT_SECS", "0") or 0)
STARTED_AT = time.time()
_last_activity = time.time()


def touch():
    global _last_activity
    _last_activity = time.time()


# ------------------------------------------------------------------ auth ----
def token_map() -> dict[str, str]:
    m: dict[str, str] = {}
    if CELL_USER and CELL_TOKEN:
        return {CELL_TOKEN: CELL_USER}
    for pair in os.environ.get("SUPERAPP_USER_TOKENS", "").split(","):
        user, _, tok = pair.strip().partition(":")
        if user and tok:
            m[tok] = user
    if os.environ.get("SUPERAPP_API_TOKEN"):
        m.setdefault(os.environ["SUPERAPP_API_TOKEN"], "default")
    return m


def resolve_token(token: str | None) -> str | None:
    if not token:
        return None
    for known, user in token_map().items():
        if hmac.compare_digest(token, known):
            return user
    if CELL_USER:
        return None   # a cell has no sign-in sessions; the gateway owns those
    return auth.resolve_session(token)


# ------------------------------------------------------------ sign-in ----
@app.get("/v1/auth/google/start")
def google_start():
    if not auth.configured():
        raise HTTPException(400, "Google sign-in is not configured on this server")
    return RedirectResponse(auth.start_url())


@app.get("/v1/auth/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(f"<p>Sign-in did not complete: {error or 'no code'}.</p>", status_code=400)
    if not auth.check_state(state):
        raise HTTPException(403, "bad sign-in state")
    try:
        identity = auth.exchange(code)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    uid, name, token = auth.complete_signin(identity)
    room_for(uid)  # provision the home now so the first message is instant
    return RedirectResponse(auth.app_redirect(uid, name, token))


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    user = resolve_token(creds.credentials if creds else None)
    if not user:
        raise HTTPException(401, "Invalid token")
    return user


# ------------------------------------------------------------- user rooms ----
class Room:
    """One user's agent plus the sockets watching it."""

    def __init__(self, user: str):
        self.user = user
        self.home = pathlib.Path(os.environ.get("SUPERAPP_HOME_ROOT", "~/.superapp/users")).expanduser() / user
        self.home.mkdir(parents=True, exist_ok=True)
        self.memory = HomeMemory(self.home)
        self.sockets: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.events: list[dict] = []
        self.store = None
        try:
            self.store = db.store_for(user)
        except Exception as e:  # noqa: BLE001
            self.events.append({"ts": time.time(), "kind": "store_error", "data": {"error": f"{type(e).__name__}: {e}"}})
        # the root agent keeps a stable id per user so its rows and transcript survive restarts
        self.agent = Agent("chat", memory=self.memory, tz=os.environ.get("SUPERAPP_TZ", "America/Chicago"),
                           on_text=self._on_text, on_event=self._on_event)
        self.agent.id = f"agent_root_{user}"
        self.agent.store = self.store
        self._load_transcript()
        self._deliver_orig = self.agent.deliver
        self.agent.deliver = self._deliver  # type: ignore[method-assign]
        self.approvals = ApprovalStore(
            on_new=lambda a: self._send({"type": "approval", "approval": a.public()}),
            on_resolved=lambda a: self._send({"type": "approval_resolved", "id": a.id, "decision": a.decision}))
        self.agent.approvals = self.approvals
        self.browser_tasks: dict[str, dict] = {}
        self._recover()
        self.scheduler = Engine(self)
        self.agent.scheduler = self.scheduler

    @property
    def on_event(self):
        return self._on_event

    def _recover(self):
        """After a restart: close out what was in flight and tell the agent, so it can pick up rather than wait forever."""
        if self.store is None:
            return
        try:
            notes = []
            for cp in self.store.pending_checkpoints():
                if cp["agent_id"] == self.agent.id:
                    notes.append("your last turn was cut off mid-work" + (f" (you were handling: {cp['payload'].get('user_text', '')[:120]!r})"
                                                                         if cp["payload"].get("user_text") else ""))
                self.store.clear_checkpoint(cp["agent_id"])
            n_sub = self.store.interrupt_open_spawns()
            n_br = self.store.interrupt_open_browser_tasks()
            n_runs = self.store.interrupt_open_runs()
            if n_sub:
                notes.append(f"{n_sub} subagent run(s) were interrupted and will not report back")
            if n_br:
                notes.append(f"{n_br} browser task(s) were interrupted; spawn again if still needed")
            if n_runs:
                notes.append(f"{n_runs} scheduled run(s) were interrupted; they are recorded as failed")
            if notes:
                self.agent.inbox.put("[Runtime] The daemon restarted. " + "; ".join(notes) + ". Check what was pending and continue or ask.")
        except Exception as e:  # noqa: BLE001
            self.events.append({"ts": time.time(), "kind": "store_error", "data": {"error": f"recover: {type(e).__name__}: {e}"}})

    # transcript persistence
    @property
    def transcript_path(self) -> pathlib.Path:
        return self.home / ".transcript.json"

    def _load_transcript(self):
        if self.store is not None:
            try:
                rows = self.store.load_transcript(self.agent.id)
                if rows:
                    self.agent.transcript = rows
                    return
            except Exception as e:  # noqa: BLE001
                self.events.append({"ts": time.time(), "kind": "store_error", "data": {"error": f"load: {type(e).__name__}: {e}"}})
        if self.transcript_path.exists():
            try:
                self.agent.transcript = json.loads(self.transcript_path.read_text())
            except json.JSONDecodeError:
                pass
            # first boot with a database: carry the file transcript into it
            if self.store is not None:
                for entry in self.agent.transcript:
                    try:
                        self.store.record_transcript_entry(self.agent.id, entry)
                    except Exception:  # noqa: BLE001
                        break

    def _save_transcript(self):
        self.transcript_path.write_text(json.dumps(self.agent.transcript, default=str))

    # fan-out
    def _send(self, frame: dict):
        if not self.loop or not self.sockets:
            return
        for ws in list(self.sockets):
            asyncio.run_coroutine_threadsafe(self._safe_send(ws, frame), self.loop)

    async def _safe_send(self, ws: WebSocket, frame: dict):
        try:
            await ws.send_text(json.dumps(frame, default=str))
        except Exception:  # noqa: BLE001
            self.sockets.discard(ws)

    def _on_text(self, s: str):
        self._send({"type": "text_delta", "text": s})

    def _on_event(self, kind: str, data: dict):
        if kind == "browser_step":
            # keep the latest card per task for late-joining clients; screenshots stay out of the event log
            self.browser_tasks[data["task_id"]] = dict(data, ts=time.time())
            self._send({"type": "browser", "task": data})
            data = {k: v for k, v in data.items() if k != "screenshot"}
        rec = {"ts": time.time(), "kind": kind, "data": data}
        self.events.append(rec)
        del self.events[:-500]
        self._send({"type": "event", "kind": kind, "data": data, "ts": rec["ts"]})

    def _deliver(self, text: str):
        """A handoff arrived (subagent report, finished command). If idle, run a turn so the agent reacts."""
        self._deliver_orig(text)
        if self.agent.status == "idle":
            threading.Thread(target=self.run_turn, args=(None,), daemon=True).start()

    # turns
    def run_turn(self, text: str | None):
        self._send({"type": "turn_start", "user_text": text})
        try:
            final = self.agent.run_turn(text)
        except Exception as e:  # noqa: BLE001
            self._send({"type": "error", "message": f"{type(e).__name__}: {e}"})
            final = ""
        self._save_transcript()
        self._send({"type": "turn_end", "text": final, "silent": bool(self.agent.silent_turn)})
        return final

    def history(self) -> list[dict]:
        out = []
        for m in self.agent.transcript:
            if m["role"] == "user":
                text = m.get("content") or ""
                tag_end = text.find("]\n") if text.startswith("[") else -1
                body = text[tag_end + 2:] if tag_end >= 0 else text
                kind = "handoff" if "[runtime handoff]" in text[:200] else "user"
                out.append({"role": kind, "text": body})
            elif m["role"] == "assistant" and (m.get("content") or "").strip():
                out.append({"role": "assistant", "text": m["content"]})
        return out


ROOMS: dict[str, Room] = {}
_rooms_lock = threading.Lock()


def room_for(user: str) -> Room:
    with _rooms_lock:
        if user not in ROOMS:
            ROOMS[user] = Room(user)
        return ROOMS[user]


def room_for_home(home: str) -> Room | None:
    target = pathlib.Path(home).resolve()
    for r in ROOMS.values():
        if r.home.resolve() == target:
            return r
    return None


# ------------------------------------------------------------ approvals ----
@app.post("/internal/approvals")
def internal_approval(body: dict, x_internal_token: str = Header("")):
    """A connector CLI asks for consent and waits here until the card is answered."""
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(401, "bad internal token")
    r = room_for_home(str(body.get("home", "")))
    if not r:
        raise HTTPException(404, "no agent for that home")
    decision = r.approvals.request(str(body.get("kind", "action")), str(body.get("title", "Approval needed")),
                                   str(body.get("subtitle", "")), list(body.get("details") or []))
    return {"decision": decision}


@app.get("/v1/approvals")
def list_approvals(user: str = Depends(current_user)):
    return {"approvals": room_for(user).approvals.pending()}


@app.get("/v1/hub")
def hub_page(user: str = Depends(current_user)):
    r = room_for(user)
    return hub.build(r.home, r.agent.tz, auth.user_record(user).get("name", "") or r.memory.read("USER.md").split("call_them:")[-1].split("\n")[0].strip())


@app.get("/v1/voice/speak")
def voice_speak(text: str, user: str = Depends(current_user)):
    r = room_for(user)
    audio = voice.tts(text, r.home / ".tts-cache")
    if not audio:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/v1/voice/status")
def voice_status(user: str = Depends(current_user)):
    return {"tts": voice.configured(), "voice_id": voice.voice_id()}


@app.get("/v1/browser/tasks")
def browser_tasks(user: str = Depends(current_user)):
    r = room_for(user)
    return {"tasks": [t.public() for t in browser_worker.TASKS.values() if t.parent.id == r.agent.id],
            "cards": list(r.browser_tasks.values())[-3:]}


@app.post("/v1/browser/tasks/{task_id}/stop")
def browser_stop(task_id: str, user: str = Depends(current_user)):
    t = browser_worker.TASKS.get(task_id)
    if not t or t.parent.id != room_for(user).agent.id:
        raise HTTPException(404, "no such task")
    t.stop()
    return {"task_id": task_id, "status": "stopped"}


@app.post("/v1/approvals/{approval_id}")
def resolve_approval(approval_id: str, body: dict, user: str = Depends(current_user)):
    a = room_for(user).approvals.resolve(approval_id, str((body or {}).get("decision", "deny")))
    if not a:
        raise HTTPException(404, "no pending approval with that id")
    return {"id": a.id, "decision": a.decision}


# ---------------------------------------------------------------- gmail ----
def _sign(action: str, home: str, ts: str) -> str:
    return hmac.new(INTERNAL_TOKEN.encode(), f"{action}|{home}|{ts}".encode(), hashlib.sha256).hexdigest()


def _verify_state(state: str, action: str) -> Room:
    try:
        act, home, ts, sig = urllib.parse.unquote(state).split("|")
    except ValueError:
        raise HTTPException(400, "bad state")
    if act != action or not hmac.compare_digest(sig, _sign(act, home, ts)) or time.time() - int(ts) > 3600:
        raise HTTPException(403, "bad or expired state")
    r = room_for_home(home)
    if not r:
        raise HTTPException(404, "no agent for that home")
    return r


def _connect_state(r: Room) -> str:
    ts = str(int(time.time()))
    return urllib.parse.quote(f"connect|{r.home}|{ts}|{_sign('connect', str(r.home), ts)}", safe="")


@app.get("/v1/connectors")
def connectors(user: str = Depends(current_user)):
    r = room_for(user)
    have = set(vault.providers(r.home))
    return {"connectors": [{"provider": "gmail", "status": "connected" if "gmail" in have else "available",
                            "configured": gmail_configured(),
                            "email": (vault.load("gmail", r.home) or {}).get("email") if "gmail" in have else None}]}


@app.get("/v1/gmail/auth-url")
def gmail_auth_url(user: str = Depends(current_user)):
    if not gmail_configured():
        raise HTTPException(400, "SUPERAPP_GOOGLE_CLIENT_ID is not set on the server")
    return {"auth_url": f"{PUBLIC_URL}/v1/gmail/connect?state={_connect_state(room_for(user))}"}


@app.get("/v1/gmail/connect")
def gmail_connect(state: str):
    """Unauthenticated link target (the user taps it from chat or the app): validates the
    signed state, then hands off to Google. The state rides along to the callback."""
    _verify_state(state, "connect")
    if not gmail_configured():
        return HTMLResponse("<p>Google OAuth is not configured on this server yet.</p>", status_code=400)
    return RedirectResponse(GmailClient().auth_url(state))


@app.get("/v1/gmail/callback")
def gmail_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(f"<p>Gmail was not connected: {error or 'no code'}.</p>", status_code=400)
    r = _verify_state(state, "connect")
    c = GmailClient()
    token = c.exchange_code(code)
    token["email"] = c.profile().get("emailAddress")
    vault.store("gmail", token, r.home)
    r.agent.deliver(f"[Connector] Gmail connected for {token['email']}. The `gmail` skill is now available.")
    return HTMLResponse(f"""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<body style='font-family:-apple-system,sans-serif;background:#F4F5F7;color:#111318;display:flex;flex-direction:column;
align-items:center;justify-content:center;height:100vh;margin:0;gap:12px'>
<div style='font-size:40px'>&#10003;</div><div style='font-size:20px'>{token['email']} connected</div>
<div style='color:#7A7E88;font-size:14px'>Returning to the app&hellip;</div>
<a href='superapp://gmail-connected' style='color:#2B6BFF'>Open the app</a>
<script>setTimeout(function() {{ location.href = 'superapp://gmail-connected'; }}, 600);</script></body>""")


@app.post("/v1/gmail/disconnect")
def gmail_disconnect(user: str = Depends(current_user)):
    return {"removed": vault.delete("gmail", room_for(user).home)}


@app.get("/v1/gmail/disconnect")
def gmail_disconnect_link(state: str):
    r = _verify_state(state, "disconnect")
    vault.delete("gmail", r.home)
    return HTMLResponse("<p>Gmail disconnected.</p>")


# --------------------------------------------------------------- cell mode ----
@app.middleware("http")
async def _activity(request, call_next):
    if request.url.path != "/health":
        touch()
    return await call_next(request)


def _busy(r: Room) -> bool:
    if r.sockets or r.agent.status == "running" or r.scheduler.running or r.approvals.pending():
        return True
    if any(t.get("status") in ("queued", "running", "needs_user") for t in r.browser_tasks.values()):
        return True
    return subagent_mod.active_count(r.agent) > 0


def cell_state() -> dict:
    """What the gateway needs to decide when to stop and wake this cell."""
    r = ROOMS.get(CELL_USER) if CELL_USER else None
    due = r.scheduler.next_due() if r else {}
    return {"user": CELL_USER, "idle_secs": int(time.time() - _last_activity), "busy": bool(r and _busy(r)),
            "uptime_secs": int(time.time() - STARTED_AT), **due}


def _idle_watch():
    while True:
        time.sleep(15)
        r = ROOMS.get(CELL_USER)
        if r is None or _busy(r) or time.time() - _last_activity < IDLE_EXIT_SECS:
            continue
        due = r.scheduler.next_due()
        if due.get("hooks_active"):
            continue   # a polling hook keeps the cell awake, as in Muse
        nxt = due.get("next_due_utc")
        if nxt and nxt - time.time() < 2 * IDLE_EXIT_SECS:
            continue   # cheaper to stay up than to stop and be woken in a moment
        print(f"cell {CELL_USER}: idle for {IDLE_EXIT_SECS}s, next job "
              f"{'in %ds' % (nxt - time.time()) if nxt else 'none'}; exiting so the machine stops", flush=True)
        os._exit(0)


@app.on_event("startup")
def _cell_boot():
    if not CELL_USER:
        return
    room_for(CELL_USER)   # warm the agent and start its scheduler even with nobody connected
    if IDLE_EXIT_SECS > 0:
        threading.Thread(target=_idle_watch, daemon=True, name="idle-watch").start()


# ------------------------------------------------------------------ REST ----
@app.get("/health")
def health():
    out = {"ok": True, "model": CONFIG.model, "users": len(ROOMS), "db": db.enabled()}
    if CELL_USER:
        out["cell"] = cell_state()
    return out


@app.get("/v1/scheduler")
def scheduler_state(user: str = Depends(current_user)):
    r = room_for(user)
    return {"status": r.scheduler.status(), "jobs": r.scheduler.list(include_disabled=True),
            "hooks": list(r.scheduler.hooks.values()), "runs": r.store.runs(None, 20) if r.store else []}


@app.get("/v1/me")
def me(user: str = Depends(current_user)):
    r = room_for(user)
    rec = auth.user_record(user)
    return {"user": user, "name": rec.get("name", ""), "email": rec.get("email"), "assistant": r.agent.assistant_name(),
            "model": CONFIG.model, "status": r.agent.status, "identity": r.memory.read("IDENTITY.md"),
            "user_md": r.memory.read("USER.md"), "google_signin": auth.configured()}


@app.get("/v1/history")
def history(user: str = Depends(current_user)):
    return {"messages": room_for(user).history()}


@app.get("/v1/activity")
def activity(user: str = Depends(current_user), limit: int = 100):
    r = room_for(user)
    subs = [{"spawn_id": s["id"], "label": s["label"], "status": s["status"]}
            for s in subagent_mod.SPAWNS.values() if s["parent"].id == r.agent.id]
    return {"events": r.events[-limit:], "subagents": subs, "status": r.agent.status}


@app.get("/v1/memory")
def memory(user: str = Depends(current_user)):
    r = room_for(user)
    return {"MEMORY.md": r.memory.read("MEMORY.md"), "today": r.memory.read_today(),
            "people": r.memory.read("memory/people/INDEX.md")}


@app.get("/v1/files")
def files(user: str = Depends(current_user)):
    root = room_for(user).home / "workspace/your_files"
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out.append({"path": p.relative_to(root).as_posix(), "bytes": st.st_size, "mtime": st.st_mtime})
    return {"files": out}


@app.get("/v1/files/{path:path}")
def file(path: str, user: str = Depends(current_user)):
    root = (room_for(user).home / "workspace/your_files").resolve()
    p = (root / path).resolve()
    if not p.is_file() or root not in p.parents:
        raise HTTPException(404, "not found")
    return FileResponse(p)


@app.get("/v1/skills")
def skills(user: str = Depends(current_user)):
    return {"skills": skills_catalog.catalog(room_for(user).home)}


# ---------------------------------------------------- feed / ideas / goals ----
# These tabs are fed by background jobs in the full product. Until those
# jobs exist, each is a JSON file under the user's home seeded with the
# "Getting started" content a brand-new reader sees, and the agent can
# rewrite the files through its ordinary file tools.
INTRO_FEED = [
    {"id": "intro-1", "kicker": "Getting started", "category": "Welcome",
     "title": "This is your feed",
     "body": "Short posts I write for you in the background, a couple of times a day, about the things you're working on and the things I notice. Tell me what you want more or less of and I'll adjust."},
    {"id": "intro-2", "kicker": "Getting started", "category": "How I work",
     "title": "I have my own computer",
     "body": "A Linux machine with a file system, a terminal, and a browser. I can research, build documents and pages, fill forms, and keep working after you close the app."},
    {"id": "intro-3", "kicker": "Getting started", "category": "Trust",
     "title": "Nothing gets sent or spent without you",
     "body": "Emails, purchases, sign-ins, and anything hard to undo stop at an approval card. Deny is always one tap away, and every action lands in the activity log behind my avatar."},
]
INTRO_IDEAS = [
    {"id": "idea-1", "icon": "📇", "title": "I can learn who matters to you",
     "body": "Tell me about the people in your life and I'll keep a page on each, so plans, birthdays, and preferences never get lost."},
    {"id": "idea-2", "icon": "🗓️", "title": "I can run a morning brief",
     "body": "A short note every morning with what's coming up, what's waiting on you, and anything I handled overnight."},
    {"id": "idea-3", "icon": "🔎", "title": "I can research anything properly",
     "body": "Give me a question and I'll fan out, read the sources, and hand you a sourced summary instead of a wall of links."},
    {"id": "idea-4", "icon": "📄", "title": "I can build you a document or a page",
     "body": "A PDF, a spreadsheet, or an interactive page you can open from the Library."},
]
INTRO_GOALS = [
    {"id": "goal-1", "title": "Get set up", "category": "Getting started", "done": False,
     "plan": ["Tell me your name and what to call you", "Connect one service", "Give me one real task"]},
]


def _json_file(user: str, name: str, seed: list) -> tuple[pathlib.Path, list]:
    p = room_for(user).home / "workspace" / f"{name}.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(seed, indent=1))
    try:
        return p, json.loads(p.read_text())
    except json.JSONDecodeError:
        return p, seed


@app.get("/v1/feed")
def feed(user: str = Depends(current_user)):
    _, posts = _json_file(user, "feed", [dict(p, ts=time.time()) for p in INTRO_FEED])
    return {"posts": posts}


@app.get("/v1/ideas")
def ideas(user: str = Depends(current_user)):
    _, items = _json_file(user, "ideas", INTRO_IDEAS)
    return {"ideas": items}


@app.get("/v1/goals")
def goals(user: str = Depends(current_user)):
    _, items = _json_file(user, "goals", INTRO_GOALS)
    return {"goals": items}


@app.put("/v1/goals")
def put_goals(body: dict, user: str = Depends(current_user)):
    p, _ = _json_file(user, "goals", INTRO_GOALS)
    items = (body or {}).get("goals")
    if not isinstance(items, list):
        raise HTTPException(400, "goals must be a list")
    p.write_text(json.dumps(items, indent=1))
    return {"goals": items}


@app.post("/v1/message")
def post_message(body: dict, user: str = Depends(current_user)):
    """Non-streaming send, for scripts and tests."""
    text = (body or {}).get("text", "").strip()
    if not text:
        raise HTTPException(400, "text required")
    return {"text": room_for(user).run_turn(text)}


# ------------------------------------------------------------- WebSocket ----
@app.websocket("/v1/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query("")):
    user = resolve_token(token)
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    touch()
    r = room_for(user)
    r.loop = asyncio.get_running_loop()
    r.sockets.add(ws)
    await ws.send_text(json.dumps({"type": "history", "messages": r.history(), "assistant": r.agent.assistant_name(),
                                   "status": r.agent.status}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            touch()
            if frame.get("type") == "message" and frame.get("text", "").strip():
                if r.agent.status == "running":
                    await ws.send_text(json.dumps({"type": "error", "message": "still working on the last message"}))
                    continue
                threading.Thread(target=r.run_turn, args=(frame["text"],), daemon=True).start()
            elif frame.get("type") == "stop":
                r.agent.closed = True
                await asyncio.sleep(0.2)
                r.agent.closed = False
    except WebSocketDisconnect:
        pass
    finally:
        r.sockets.discard(ws)
        touch()
