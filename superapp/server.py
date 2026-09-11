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
import httpx
from typing import Any
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import CONFIG
from .memory.files import HomeMemory
from .prompts import skills_catalog
from .tools import local, memory_tools  # noqa: F401  registers handlers
from .agent import subagents  # noqa: F401
from .browser import worker as browser_worker, web as browser_web, live as browser_live  # noqa: F401
from .agent.loop import Agent
from .agent import subagents as subagent_mod
from . import auth, db, hub, voice
from .approvals import Approval, ApprovalStore
from .scheduler import tools as scheduler_tools  # noqa: F401  registers cron.*, hooks.*, muse.nothing_to_do
from .scheduler.engine import Engine
from .connectors import vault
from .connectors.gmail import CALENDAR_SCOPE, GmailClient, configured as gmail_configured
from .cells import gateway

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
    if CELLS:
        threading.Thread(target=CELLS.ensure_cell, args=(uid,), daemon=True).start()  # machine + volume for a new user
    else:
        room_for(uid)  # provision the home now so the first message is instant
    return RedirectResponse(auth.app_redirect(uid, name, token))


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    user = resolve_token(creds.credentials if creds else None)
    if not user:
        raise HTTPException(401, "Invalid token")
    return user


# ----------------------------------------------------------------- gateway ----
# In gateway mode this process runs no agent: /v1/* and the WebSocket are proxied
# to the user's own cell (a machine per user); sign-in and the cell registry stay here.
CELLS: gateway.Cells | None = None
if gateway.enabled():
    CELLS = gateway.Cells(resolve_token, pathlib.Path(os.environ.get("SUPERAPP_HOME_ROOT", "~/.superapp/users")).expanduser())
    app.add_middleware(gateway.GatewayMiddleware, cells=CELLS)


@app.post("/internal/cells/state")
def cell_report(body: dict, x_cell_token: str = Header("")):
    """A cell reports its idle/next-due state on its way out, so the gateway knows when to wake it."""
    if not CELLS or not CELLS.report_state(str((body or {}).get("user", "")), x_cell_token, body or {}):
        raise HTTPException(403, "unknown cell")
    return {"ok": True}


@app.post("/internal/sessions/import")
def sessions_import(body: dict, x_internal_token: str = Header("")):
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(403, "bad internal token")
    return auth.import_data(body or {})


@app.post("/internal/cells/{user}/import")
async def cell_import_via_gateway(user: str, request: Request, x_internal_token: str = Header("")):
    """Migration: forward an export bundle (home tar + db.sql + meta.json) to the user's cell."""
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(403, "bad internal token")
    if not CELLS:
        raise HTTPException(400, "not a gateway")
    body = await request.body()
    cell = await asyncio.to_thread(CELLS.ensure_awake, user)
    r = await asyncio.to_thread(lambda: httpx.post(CELLS.addr(cell) + "/internal/import", content=body,
                                                    headers={"X-Cell-Token": cell["token"]}, timeout=600))
    cell["last_state"] = None   # the cell restarts itself after an import
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@app.post("/internal/import")
async def cell_import(request: Request, x_cell_token: str = Header("")):
    """Inside a cell: replace this user's home and database with an exported bundle, then restart."""
    if not CELL_USER or not hmac.compare_digest(x_cell_token, CELL_TOKEN or ""):
        raise HTTPException(403, "not a cell or bad cell token")
    body = await request.body()
    return await asyncio.to_thread(_do_import, body)


def _do_import(body: bytes) -> dict:
    import io, shutil, subprocess, tarfile, tempfile
    home = pathlib.Path(os.environ.get("SUPERAPP_HOME_ROOT", "~/.superapp/users")).expanduser() / CELL_USER
    out: dict[str, Any] = {"user": CELL_USER}
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
            tar.extractall(td, filter="data")
        work = pathlib.Path(td)
        meta = json.loads((work / "meta.json").read_text()) if (work / "meta.json").exists() else {}
        r = ROOMS.get(CELL_USER)
        if r:
            r.scheduler._stop.set()
        src = work / "home"
        if src.exists():
            for item in src.iterdir():
                dst = home / item.name
                if item.is_dir():
                    shutil.copytree(item, dst, dirs_exist_ok=True, symlinks=True)
                else:
                    shutil.copy2(item, dst)
            out["home_entries"] = len(list(src.iterdir()))
        if (work / "db.sql").exists():
            dbname = db._dbname(CELL_USER)
            admin = "postgresql://superapp@127.0.0.1:5432/postgres"
            subprocess.run(["psql", admin, "-v", "ON_ERROR_STOP=1", "-c",
                            f"select pg_terminate_backend(pid) from pg_stat_activity where datname='{dbname}' and pid<>pg_backend_pid()",
                            "-c", f'drop database if exists "{dbname}"', "-c", f'create database "{dbname}"'], check=True, capture_output=True)
            res = subprocess.run(["psql", admin.replace("/postgres", f"/{dbname}"), "-q", "-f", str(work / "db.sql")],
                                 capture_output=True, text=True)
            out["db_restored"] = res.returncode == 0
            out["db_errors"] = res.stderr.count("ERROR")
        if meta.get("vault_key_old"):
            out["vault_rekeyed"] = vault.rekey(home, meta["vault_key_old"])
    out["restarting"] = True
    threading.Timer(1.0, lambda: os._exit(0)).start()   # the gateway boots us fresh on the next request
    return out


@app.post("/v1/push/register")
def push_register(body: dict, user: str = Depends(current_user)):
    """The app registers its device token here (gateway-side; a cell never sees tokens)."""
    if not CELLS:
        return {"registered": False, "reason": "push is handled by the gateway"}
    token = str((body or {}).get("token", "")).strip()
    if not token:
        raise HTTPException(400, "token required")
    n = CELLS.register_push(user, token, str((body or {}).get("platform", "ios")), str((body or {}).get("env", "production")))
    return {"registered": True, "devices": n, "apns": CELLS.apns.configured()}


@app.post("/v1/push/unregister")
def push_unregister(body: dict, user: str = Depends(current_user)):
    if not CELLS:
        return {"removed": False}
    return {"removed": CELLS.unregister_push(user, str((body or {}).get("token", "")))}


@app.post("/internal/cells/notify")
def cell_notify(body: dict, x_cell_token: str = Header("")):
    """A cell reports something worth a notification: a finished job, an approval, a proactive message."""
    if not CELLS:
        raise HTTPException(400, "not a gateway")
    b = body or {}
    try:
        return CELLS.notify(str(b.get("user", "")), x_cell_token, str(b.get("title", "")), str(b.get("body", "")),
                            b.get("data") or {}, b.get("thread_id"))
    except PermissionError:
        raise HTTPException(403, "unknown cell")


@app.get("/internal/cells")
def cells_list(x_internal_token: str = Header("")):
    if not hmac.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(403, "bad internal token")
    return {"cells": CELLS.public() if CELLS else []}


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
        # deferred tool namespaces the root agent has loaded survive restarts with the transcript they belong to
        self._loaded_path = self.home / ".runtime" / "loaded_tools.json"
        try:
            self.agent.loaded_ns = set(json.loads(self._loaded_path.read_text()))
        except (OSError, ValueError):
            self.agent.loaded_ns = set()
        def _persist(ns: set[str]):
            self._loaded_path.parent.mkdir(parents=True, exist_ok=True)
            self._loaded_path.write_text(json.dumps(sorted(ns)))
        self.agent.on_tools_loaded = _persist
        self._load_transcript()
        self._deliver_orig = self.agent.deliver
        self.agent.deliver = self._deliver  # type: ignore[method-assign]
        self.approvals = ApprovalStore(
            on_new=lambda a: (self._send({"type": "approval", "approval": a.public()}),
                              self.notify("Needs your approval", a.title, {"tab": "chat", "approval": a.id}, thread_id="approvals")),
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
            prev = self.browser_tasks.get(data["task_id"], {})
            self.browser_tasks[data["task_id"]] = dict(data, ts=time.time())
            self._send({"type": "browser", "task": data})
            if data.get("status") == "needs_user" and prev.get("status") != "needs_user" and data.get("status_title") != "You're in control":
                self.notify("Muse needs you in the browser", (data.get("title") or "A browser task") + " is waiting for you.",
                            {"tab": "chat", "browser": data["task_id"]}, thread_id="browser")
            data = {k: v for k, v in data.items() if k != "screenshot"}
        rec = {"ts": time.time(), "kind": kind, "data": data}
        self.events.append(rec)
        del self.events[:-500]
        # Work done by a scheduled worker, a hook worker, or a subagent is background: the app logs it
        # in the activity sheet but must not show it as the chat agent still working on the user's turn.
        agent = data.get("agent") if isinstance(data, dict) else None
        background = kind in ("scheduled_run", "scheduled_skip", "hook_poll", "hook_wake") or (agent is not None and agent != self.agent.id)
        self._send({"type": "event", "kind": kind, "data": data, "ts": rec["ts"], "background": background})

    def _deliver(self, text: str):
        """A handoff arrived (subagent report, finished command). If idle, run a turn so the agent reacts."""
        self._deliver_orig(text)
        if self.agent.status == "idle":
            threading.Thread(target=self.run_turn, args=(None,), daemon=True).start()

    def notify(self, title: str, body: str, data: dict | None = None, thread_id: str | None = None):
        """Reach the person on their phone when nobody is looking at the app. Only in a cell, and only when
        no socket is attached: an open app already shows everything live."""
        if self.sockets or not CELL_USER or not os.environ.get("SUPERAPP_GATEWAY_URL"):
            return
        def go():
            try:
                httpx.post(os.environ["SUPERAPP_GATEWAY_URL"].rstrip("/") + "/internal/cells/notify",
                           json={"user": CELL_USER, "title": title, "body": body, "data": data or {}, "thread_id": thread_id},
                           headers={"X-Cell-Token": CELL_TOKEN or ""}, timeout=15)
            except Exception as e:  # noqa: BLE001
                self.events.append({"ts": time.time(), "kind": "push_error", "data": {"error": f"{type(e).__name__}: {e}"}})
        threading.Thread(target=go, daemon=True).start()

    # turns
    def run_turn(self, text: str | None):
        if text is not None:
            self.scheduler.note_activity()
        self._send({"type": "turn_start", "user_text": text})
        try:
            final = self.agent.run_turn(text)
        except Exception as e:  # noqa: BLE001
            self._send({"type": "error", "message": f"{type(e).__name__}: {e}"})
            final = ""
        self._save_transcript()
        self._send({"type": "turn_end", "text": final, "silent": bool(self.agent.silent_turn)})
        if text is None and final and not self.agent.silent_turn:
            # the agent spoke on its own (a job result, a hook, a finished background task): tell the phone
            name = self.agent.assistant_name()
            self.notify("Muse" if name == "your assistant" else name, final.strip().splitlines()[0][:200], {"tab": "chat"}, thread_id="chat")
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


# ------------------------------------------------------- browser connector ----
def _active_task(r: Room):
    for t in browser_worker.TASKS.values():
        if t.parent.id == r.agent.id and t.driver is not None and t.status in ("queued", "running", "needs_user"):
            return t
    return None


def _live_state(r: Room) -> dict:
    """What the app's live browser view shows: the task's page, a free session, or nothing."""
    t = _active_task(r)
    if t is not None:
        base = {"mode": "task", "task_id": t.id, "status": t.status, "status_title": t.status_title, "title": t.title,
                "question": t.question, "can_control": t.status == "needs_user"}
        if t.status == "needs_user":
            try:
                return {**base, **t.command({"type": "state"}, timeout=20)}
            except Exception:  # noqa: BLE001
                pass
        return {**base, "url": t.url, "screenshot": t.screenshot, **browser_live.VIEW}
    s = browser_live.current(r.home)
    if s is not None:
        return {"mode": "free", "can_control": True, **s.command({"type": "state"}, timeout=20)}
    return {"mode": "none", "can_control": False, "url": "", "title": "", "screenshot": "", **browser_live.VIEW}


@app.get("/v1/browser/live")
def browser_live_state(user: str = Depends(current_user)):
    return _live_state(room_for(user))


@app.post("/v1/browser/live/open")
def browser_live_open(user: str = Depends(current_user)):
    """Open the agent's browser for the user with no task running: sign into sites, check something."""
    r = room_for(user)
    if _active_task(r) is None:
        try:
            browser_live.open_session(r.home)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"could not open the browser: {e}")
    return _live_state(r)


@app.post("/v1/browser/live/close")
def browser_live_close(user: str = Depends(current_user)):
    r = room_for(user)
    browser_live.close_for(r.home)
    return {"closed": True}


@app.post("/v1/browser/live/input")
def browser_live_input(body: dict, user: str = Depends(current_user)):
    """One gesture from the phone: tap, type, key, scroll, navigate, back."""
    r = room_for(user)
    cmd = body or {}
    t = _active_task(r)
    host = t if t is not None else browser_live.current(r.home)
    if host is None:
        raise HTTPException(409, "no browser is open")
    if t is not None and t.status != "needs_user":
        raise HTTPException(409, "Muse is driving this page; take over first")
    try:
        st = host.command(cmd, timeout=30)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"browser did not respond: {e}")
    return {**_live_state(r), **{k: v for k, v in st.items() if k in ("url", "title", "screenshot", "error")}}


@app.post("/v1/browser/tasks/{task_id}/takeover")
def browser_takeover(task_id: str, user: str = Depends(current_user)):
    r = room_for(user)
    t = browser_worker.TASKS.get(task_id)
    if not t or t.parent.id != r.agent.id:
        raise HTTPException(404, "no such task")
    try:
        t.takeover()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    for _ in range(60):   # the worker finishes its current step, then hands the page over
        if t.status == "needs_user":
            break
        time.sleep(0.5)
    return _live_state(r)


@app.post("/v1/browser/tasks/{task_id}/handback")
def browser_handback(task_id: str, body: dict, user: str = Depends(current_user)):
    r = room_for(user)
    t = browser_worker.TASKS.get(task_id)
    if not t or t.parent.id != r.agent.id:
        raise HTTPException(404, "no such task")
    try:
        t.handback(str((body or {}).get("note", "")))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"task_id": task_id, "status": "running"}


def _cookie_host(r: Room):
    t = _active_task(r)
    if t is not None:
        return t if t.status == "needs_user" else None   # a running worker owns the thread
    return browser_live.current(r.home)


@app.get("/v1/browser/logins")
def browser_logins(user: str = Depends(current_user)):
    r = room_for(user)
    return {"sites": browser_live.logins(r.home, host=_cookie_host(r))}


@app.post("/v1/browser/logins/forget")
def browser_forget(body: dict, user: str = Depends(current_user)):
    r = room_for(user)
    domain = str((body or {}).get("domain", "")).strip()
    if not domain:
        raise HTTPException(400, "domain required")
    t = _active_task(r)
    if t is not None and t.status != "needs_user":
        raise HTTPException(409, "a browser task is running; try again when it finishes")
    try:
        browser_live.forget(r.home, domain, host=t or browser_live.current(r.home))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"could not clear cookies: {e}")
    return {"forgot": domain, "sites": browser_live.logins(r.home, host=_cookie_host(r))}


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
    """Live connectors. Gmail and Google Calendar share one Google sign-in; Calendar shows as connected
    once that account has granted the calendar scope (an older Gmail-only consent can be re-run to add it)."""
    r = room_for(user)
    tok = vault.load("gmail", r.home) or {}
    have_gmail = bool(tok)
    have_cal = have_gmail and CALENDAR_SCOPE in (tok.get("scopes") or [])
    return {"connectors": [
        {"provider": "gmail", "status": "connected" if have_gmail else "available", "configured": gmail_configured(),
         "email": tok.get("email") if have_gmail else None},
        {"provider": "google_calendar", "status": "connected" if have_cal else "available", "configured": gmail_configured(),
         "email": tok.get("email") if have_cal else None, "connect_via": "gmail",
         "note": None if have_cal or not have_gmail else "Reconnect Google to add calendar access."},
    ]}


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
    services = ["Gmail"] + (["Google Calendar"] if CALENDAR_SCOPE in (token.get("scopes") or []) else [])
    r.agent.deliver(f"[Connector] {' and '.join(services)} connected for {token['email']}. "
                    f"The `gmail`{' and `google_calendar`' if len(services) > 1 else ''} skill{'s are' if len(services) > 1 else ' is'} now available.")
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
        if os.environ.get("SUPERAPP_GATEWAY_URL"):
            try:
                import httpx
                httpx.post(os.environ["SUPERAPP_GATEWAY_URL"].rstrip("/") + "/internal/cells/state", json=cell_state(),
                           headers={"X-Cell-Token": CELL_TOKEN or ""}, timeout=10)
            except Exception as e:  # noqa: BLE001
                print(f"cell {CELL_USER}: could not report state to the gateway: {e}", flush=True)
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
    if CELLS:
        out["gateway"] = True
        out["cells"] = len(CELLS.cells)
    return out


@app.get("/v1/scheduler")
def scheduler_state(user: str = Depends(current_user)):
    r = room_for(user)
    return {"status": r.scheduler.status(), "jobs": r.scheduler.list(include_disabled=True),
            "hooks": list(r.scheduler.hooks.values()), "runs": r.store.runs(None, 20) if r.store else []}


def _field(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _set_fields(text: str, values: dict[str, str]) -> str:
    """Fill `key: value` lines in a standing file, keeping everything else as it is."""
    out, seen = [], set()
    for line in text.splitlines():
        key = line.split(":", 1)[0].strip().lower() if ":" in line and not line.startswith("#") else None
        if key in values:
            out.append(f"{key}: {values[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in values.items():
        if key not in seen:
            out.append(f"{key}: {val}")
    return "\n".join(out).rstrip("\n") + "\n"


def onboarded(r: Room) -> bool:
    return bool(_field(r.memory.read("USER.md"), "name"))


@app.get("/v1/me")
def me(user: str = Depends(current_user)):
    r = room_for(user)
    rec = auth.user_record(user)
    return {"user": user, "name": rec.get("name", ""), "email": rec.get("email"), "assistant": r.agent.assistant_name(),
            "model": CONFIG.model, "status": r.agent.status, "identity": r.memory.read("IDENTITY.md"),
            "user_md": r.memory.read("USER.md"), "google_signin": auth.configured(), "onboarded": onboarded(r)}


@app.post("/v1/onboarding")
def onboarding(body: dict, user: str = Depends(current_user)):
    """First-run setup from the app: who the user is, what to call the agent, what is on their plate.
    Writes the standing files, then hands the agent an opening so it greets in its own voice."""
    import zoneinfo
    r = room_for(user)
    b = {k: str((body or {}).get(k, "")).strip()[:200] for k in ("name", "call_them", "assistant", "vibe", "timezone")}
    plate = str((body or {}).get("plate", "")).strip()[:2000]
    if not b["name"]:
        raise HTTPException(400, "name required")
    call = b["call_them"] or b["name"].split()[0]
    assistant = b["assistant"] or "Muse"
    vibe = b["vibe"] or "warm and direct"
    tz = b["timezone"]
    try:
        zoneinfo.ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        tz = r.agent.tz
    r.agent.tz = tz
    (r.home / "USER.md").write_text(_set_fields(r.memory.read("USER.md"), {"name": b["name"], "call_them": call, "timezone": tz}))
    (r.home / "IDENTITY.md").write_text(_set_fields(r.memory.read("IDENTITY.md"), {"name": assistant, "vibe": vibe}))
    r.memory.append_daily(f"Onboarding: user {b['name']} (call them {call}), agent named {assistant}, vibe {vibe}, timezone {tz}."
                          + (f" On their plate: {plate}" if plate else ""))
    r._deliver(f"[Onboarding complete] {b['name']} just finished setup and is looking at the chat. Call them {call}. "
               f"They named you {assistant} and asked for a {vibe} vibe; USER.md and IDENTITY.md are already written. "
               + (f"What is on their plate right now, in their words: {plate!r}. " if plate else "They did not say what is on their plate yet. ")
               + "Greet them in two or three sentences in your own voice, reflect back the one thing that matters most from what they said, "
               "and name the first concrete thing you will do. If something durable came up, record it in MEMORY.md. No lists, no headings.")
    return {"ok": True, "assistant": assistant, "call_them": call, "timezone": tz}


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
    if CELLS:
        return await CELLS.bridge_ws(ws, token)
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
