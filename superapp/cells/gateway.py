"""The gateway: Muse's control plane in front of per-user cells.

In gateway mode (SUPERAPP_CELLS=fly) this process does not run any agent. It
signs people in, keeps a registry of user -> machine, creates a volume and a
machine for a new user, proxies every /v1/* request and the WebSocket to that
user's cell over the private network, wakes a stopped cell on demand, and starts
cells shortly before their next scheduled job. Cells report their idle/next-due
state here when they exit.

Registry: <HOME_ROOT>/.cells.json. Each entry holds the machine id, volume id,
private address, the cell's bearer token, and its vault key.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, secrets, threading, time, urllib.parse
from typing import Callable
import httpx
import websockets
from cryptography.fernet import Fernet
from .fly import FlyMachines, FlyError
from .apns import APNs

CELL_PORT = 18792
# What a cell needs from the gateway's environment. Secrets travel once, at machine creation.
PASSTHROUGH = ["META_API_KEY", "MODEL_API_KEY", "MODEL", "MODEL_API_BASE",
               "SUPERAPP_GOOGLE_CLIENT_ID", "SUPERAPP_GOOGLE_CLIENT_SECRET", "SUPERAPP_GOOGLE_REDIRECT_URI",
               "SUPERAPP_GMAIL_SCOPE_TIER", "SUPERAPP_GMAIL_API_BASE", "SUPERAPP_PUBLIC_URL", "SUPERAPP_TZ",
               "SUPERAPP_ELEVENLABS_API_KEY", "SUPERAPP_ELEVENLABS_MODEL", "SUPERAPP_VOICE_ID",
               "SUPERAPP_CELL_IDLE_EXIT_SECS", "SUPERAPP_LOG_LEVEL"]
STATE_PATHS = ("/v1/gmail/connect", "/v1/gmail/callback", "/v1/gmail/disconnect")   # unauthenticated, carry a signed state
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "upgrade", "host", "authorization"}


def enabled() -> bool:
    return os.environ.get("SUPERAPP_CELLS", "").lower() == "fly"


class Cells:
    def __init__(self, resolve_user: Callable[[str | None], str | None], home_root: pathlib.Path):
        self.resolve_user = resolve_user
        self.path = home_root / ".cells.json"
        home_root.mkdir(parents=True, exist_ok=True)
        self.cells: dict[str, dict] = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.fly = FlyMachines()
        self.region = os.environ.get("FLY_CELLS_REGION", "ord")
        self.image = os.environ.get("FLY_CELLS_IMAGE", "registry.fly.io/muse-cells:latest")
        self.addr_template = os.environ.get("FLY_CELL_ADDR_TEMPLATE", "http://[{private_ip}]:%d" % CELL_PORT)
        self.gateway_url = os.environ.get("SUPERAPP_GATEWAY_URL", "")
        self.wake_lead = int(os.environ.get("SUPERAPP_CELL_WAKE_LEAD_SECS", "120"))
        self._lock = threading.Lock()
        self._user_locks: dict[str, threading.Lock] = {}
        self._failed: dict[str, tuple[float, str]] = {}   # user -> (when, why); recent failures answer fast
        self.retry_after = int(os.environ.get("SUPERAPP_CELL_RETRY_SECS", "30"))
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15))
        self.push_path = home_root / ".push.json"
        self.push: dict[str, list[dict]] = json.loads(self.push_path.read_text()) if self.push_path.exists() else {}
        self.apns = APNs()
        threading.Thread(target=self._wake_loop, daemon=True, name="cell-wake").start()

    # ----------------------------------------------------------- registry --
    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cells, indent=1))
        tmp.replace(self.path)

    def _ulock(self, user: str) -> threading.Lock:
        with self._lock:
            return self._user_locks.setdefault(user, threading.Lock())

    def addr(self, cell: dict) -> str:
        return self.addr_template.format(**cell)

    def public(self) -> list[dict]:
        return [{k: v for k, v in c.items() if k not in ("token", "vault_key")} for c in self.cells.values()]

    # --------------------------------------------------------- provisioning --
    def cell_env(self, user: str, cell: dict) -> dict:
        env = {k: os.environ[k] for k in PASSTHROUGH if os.environ.get(k)}
        if "SUPERAPP_CELL_IDLE_EXIT_SECS" in env:
            env["SUPERAPP_IDLE_EXIT_SECS"] = env.pop("SUPERAPP_CELL_IDLE_EXIT_SECS")
        env.update({"SUPERAPP_CELL_USER": user, "SUPERAPP_CELL_TOKEN": cell["token"], "SUPERAPP_VAULT_KEY": cell["vault_key"],
                    "SUPERAPP_HOME_ROOT": "/data/users", "SUPERAPP_PORT": str(CELL_PORT)})
        if self.gateway_url:
            env["SUPERAPP_GATEWAY_URL"] = self.gateway_url
        return env

    def ensure_cell(self, user: str) -> dict:
        """The user's machine, created on first use: a volume, then a machine with the cell image."""
        with self._ulock(user):
            if user in self.cells:
                return self.cells[user]
            cell = {"user": user, "token": secrets.token_urlsafe(24), "vault_key": Fernet.generate_key().decode(),
                    "created_at": time.time(), "next_due_utc": None, "last_state": None}
            vol = self.fly.create_volume(f"cell_{_slug(user)}", self.region, int(os.environ.get("FLY_CELLS_VOLUME_GB", "10")))
            cell["volume_id"] = vol["id"]
            config = {"image": self.image, "env": self.cell_env(user, cell),
                      "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": int(os.environ.get("FLY_CELLS_MEMORY_MB", "2048"))},
                      "mounts": [{"volume": vol["id"], "path": "/data"}],
                      "restart": {"policy": "on-failure", "max_retries": 3}, "auto_destroy": False,
                      "metadata": {"muse_user": user}}
            m = self.fly.create_machine(self.region, config, name=f"cell-{_slug(user)}")
            cell.update({"machine_id": m["id"], "private_ip": m.get("private_ip", ""), "last_state": m.get("state")})
            self.cells[user] = cell
            self._save()
            print(f"gateway: created cell for {user}: machine {m['id']} volume {vol['id']}", flush=True)
            return cell

    def awake(self, user: str) -> dict:
        """ensure_awake with a short memory of failures, so a broken token or a dead machine does not
        turn every app request into a Fly API call."""
        f = self._failed.get(user)
        if f and time.time() - f[0] < self.retry_after:
            raise FlyError(f[1])
        try:
            cell = self.ensure_awake(user)
        except Exception as e:  # noqa: BLE001
            self._failed[user] = (time.time(), f"{type(e).__name__}: {e}")
            print(f"gateway: cell {user} unavailable: {type(e).__name__}: {e}", flush=True)
            raise
        self._failed.pop(user, None)
        return cell

    def ensure_awake(self, user: str, timeout: int = 150) -> dict:
        """Start the user's machine if it is stopped and wait until its daemon answers /health."""
        cell = self.ensure_cell(user)
        with self._ulock(user):
            m = self.fly.get(cell["machine_id"])
            cell["last_state"] = m.get("state")
            if m.get("private_ip"):
                cell["private_ip"] = m["private_ip"]
            if m.get("state") not in ("started", "starting", "created", "replacing"):
                print(f"gateway: waking cell {user} ({m.get('state')})", flush=True)
                self.fly.start(cell["machine_id"])
            if m.get("state") != "started":   # a just-created or starting machine only needs waiting for
                try:
                    self.fly.wait(cell["machine_id"], "started", 60)
                except FlyError:
                    self.fly.wait_state(cell["machine_id"], "started", 60)
                m = self.fly.get(cell["machine_id"])
                cell["private_ip"] = m.get("private_ip") or cell["private_ip"]
                cell["last_state"] = m.get("state")
            deadline = time.time() + timeout
            url = self.addr(cell) + "/health"
            while time.time() < deadline:
                try:
                    r = httpx.get(url, timeout=5)
                    if r.status_code == 200 and r.json().get("ok"):
                        st = r.json().get("cell") or {}
                        cell["next_due_utc"] = st.get("next_due_utc")
                        cell["last_seen"] = time.time()
                        self._save()
                        return cell
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(1)
            raise FlyError(f"cell for {user} did not become healthy in {timeout}s")

    # --------------------------------------------------------------- push --
    def register_push(self, user: str, token: str, platform: str, env: str) -> int:
        rows = [r for r in self.push.get(user, []) if r["token"] != token]
        rows.append({"token": token, "platform": platform, "env": env if env in ("production", "sandbox") else "production",
                     "updated_at": time.time()})
        self.push[user] = rows[-5:]   # a person has a handful of devices, not a fleet
        self._save_push()
        return len(self.push[user])

    def unregister_push(self, user: str, token: str) -> bool:
        before = len(self.push.get(user, []))
        self.push[user] = [r for r in self.push.get(user, []) if r["token"] != token]
        self._save_push()
        return len(self.push[user]) < before

    def _save_push(self):
        tmp = self.push_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.push, indent=1))
        tmp.replace(self.push_path)

    def notify(self, user: str, token: str, title: str, body: str, data: dict | None = None, thread_id: str | None = None) -> dict:
        """A cell asks the gateway to reach the person: every registered device, dead tokens dropped."""
        cell = self.cells.get(user)
        if not cell or not secrets.compare_digest(token, cell["token"]):
            raise PermissionError("unknown cell")
        results = []
        for row in list(self.push.get(user, [])):
            if row.get("platform") != "ios":
                continue
            res = self.apns.send(row["token"], row.get("env", "production"), title, body, data, thread_id)
            if res == "gone":
                self.unregister_push(user, row["token"])
            results.append(res)
        print(f"push: {user} {title!r} -> {results or 'no devices'}", flush=True)
        return {"devices": len(results), "results": results}

    # ------------------------------------------------------------- waking --
    def report_state(self, user: str, token: str, state: dict) -> bool:
        cell = self.cells.get(user)
        if not cell or not secrets.compare_digest(token, cell["token"]):
            return False
        cell["next_due_utc"] = state.get("next_due_utc")
        cell["last_report"] = time.time()
        self._save()
        return True

    def _wake_loop(self):
        while True:
            time.sleep(30)
            now = time.time()
            for user, cell in list(self.cells.items()):
                try:
                    nxt = cell.get("next_due_utc")
                    if nxt and nxt - now < self.wake_lead and (cell.get("last_state") != "started" or now - cell.get("last_seen", 0) > 60):
                        st = self.fly.state(cell["machine_id"])
                        cell["last_state"] = st
                        if st != "started":
                            print(f"gateway: job due in {int(nxt - now)}s, waking cell {user}", flush=True)
                            self.awake(user)
                    elif cell.get("last_state") == "started" and now - cell.get("last_seen", 0) > 60:
                        r = httpx.get(self.addr(cell) + "/health", timeout=5)
                        st = (r.json().get("cell") or {}) if r.status_code == 200 else {}
                        cell["next_due_utc"] = st.get("next_due_utc", cell.get("next_due_utc"))
                        cell["last_seen"] = now
                except Exception as e:  # noqa: BLE001
                    cell["last_state"] = None
                    print(f"gateway: wake loop {user}: {type(e).__name__}: {e}", flush=True)
            self._save()

    # -------------------------------------------------------------- proxy --
    def user_for_scope(self, scope) -> str | None:
        path = scope["path"]
        query = dict(urllib.parse.parse_qsl(scope.get("query_string", b"").decode()))
        if path in STATE_PATHS and "state" in query:
            return user_from_state(query["state"])
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else query.get("token")
        return self.resolve_user(token)

    def routes(self, path: str) -> bool:
        return (path.startswith("/v1/") and not path.startswith("/v1/auth/") and not path.startswith("/v1/push/")
                and path != "/v1/ws")

    async def handle_http(self, scope, receive, send):
        user = self.user_for_scope(scope)
        if not user:
            return await _json(send, 401, {"detail": "Invalid token"})
        try:
            cell = await asyncio.to_thread(self.awake, user)
        except Exception as e:  # noqa: BLE001
            return await _json(send, 503, {"detail": f"cell unavailable: {e}"})
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        headers = {k.decode(): v.decode() for k, v in scope["headers"] if k.decode().lower() not in HOP_HEADERS}
        headers["Authorization"] = f"Bearer {cell['token']}"
        url = self.addr(cell) + scope["path"] + ("?" + scope["query_string"].decode() if scope["query_string"] else "")
        try:
            req = self.http.build_request(scope["method"], url, headers=headers, content=body)
            resp = await self.http.send(req, stream=True)
        except Exception as e:  # noqa: BLE001
            return await _json(send, 502, {"detail": f"cell error: {type(e).__name__}: {e}"})
        out_headers = [(k.lower().encode(), v.encode()) for k, v in resp.headers.multi_items()
                       if k.lower() not in ("transfer-encoding", "connection")]
        await send({"type": "http.response.start", "status": resp.status_code, "headers": out_headers})
        try:
            async for chunk in resp.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        finally:
            await resp.aclose()
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        cell["last_seen"] = time.time()

    async def bridge_ws(self, ws, token: str):
        """The app's socket <-> the cell's socket, both directions, until either side closes."""
        user = self.resolve_user(token)
        if not user:
            await ws.close(code=4401)
            return
        await ws.accept()
        # Read the app's frames from the start so nothing typed while the cell boots is lost;
        # they are replayed to the cell once it is up. None marks the client leaving.
        inbox: asyncio.Queue = asyncio.Queue()

        async def reader():
            try:
                while True:
                    await inbox.put(await ws.receive_text())
            except Exception:  # noqa: BLE001
                await inbox.put(None)

        reader_task = asyncio.create_task(reader())
        # Hold the socket while the cell comes up. Closing it on failure would make the app
        # reconnect immediately and post an error bubble each time; instead report once and
        # keep retrying on this connection until the client goes away.
        cell = None
        reported = False
        try:
            while cell is None:
                try:
                    cell = await asyncio.to_thread(self.awake, user)
                except Exception as e:  # noqa: BLE001
                    if not reported:
                        await ws.send_text(json.dumps({"type": "error", "message": f"Your cell is unavailable: {e}. Retrying in the background."}))
                        reported = True
                    for _ in range(self.retry_after):
                        await asyncio.sleep(1)
                        if reader_task.done():
                            return
                        try:
                            await ws.send_text(json.dumps({"type": "ping"}))
                        except Exception:  # noqa: BLE001  client left
                            return
            if reported:
                await ws.send_text(json.dumps({"type": "error", "message": "Your cell is up."}))
            upstream_url = self.addr(cell).replace("http", "ws", 1) + f"/v1/ws?token={urllib.parse.quote(cell['token'])}"
            async with websockets.connect(upstream_url, max_size=None) as up:
                async def app_to_cell():
                    while True:
                        item = await inbox.get()
                        if item is None:
                            return
                        await up.send(item)

                async def cell_to_app():
                    async for msg in up:
                        await ws.send_text(msg if isinstance(msg, str) else msg.decode())
                        cell["last_seen"] = time.time()

                done, pending = await asyncio.wait([asyncio.create_task(app_to_cell()), asyncio.create_task(cell_to_app())],
                                                   return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
        except Exception:  # noqa: BLE001  (client disconnects arrive as exceptions from either side)
            pass
        finally:
            reader_task.cancel()
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass


class GatewayMiddleware:
    """Raw ASGI: hands /v1/* HTTP traffic to the user's cell; everything else stays local."""

    def __init__(self, app, cells: Cells):
        self.app, self.cells = app, cells

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.cells.routes(scope["path"]):
            return await self.cells.handle_http(scope, receive, send)
        await self.app(scope, receive, send)


def user_from_state(state: str) -> str | None:
    """Gmail connect/callback states are `connect|<home>|ts|sig`; the home's last segment is the user.
    The cell verifies the signature itself; the gateway only needs to know where to send it."""
    try:
        _, home, _, _ = urllib.parse.unquote(state).split("|")
        return pathlib.PurePosixPath(home).name or None
    except ValueError:
        return None


def _slug(user: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in user.lower())[:40]


async def _json(send, status: int, body: dict):
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())]})
    await send({"type": "http.response.body", "body": data})
