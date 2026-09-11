"""The Browser connector: live control of the agent's own browser.

Two hosts can own the Chromium profile: a browser task (worker.TaskRunner) or a
free session opened from the Connectors screen so the user can sign into sites
the agent will use later. Both execute `execute()` commands on the thread that
owns the Driver (Playwright's sync API is thread-affine), and both answer
`state()`: the current URL, title, and a screenshot the app draws and taps on.

Signed-in sites come straight from the profile's cookie database, so they can be
listed without launching Chromium.
"""
from __future__ import annotations
import pathlib, queue, shutil, sqlite3, tempfile, threading, time
from .driver import Driver

LIVE_IDLE_S = 300           # a free session closes after five quiet minutes
VIEW = {"width": 1024, "height": 1100}
LIVE: dict[str, "LiveSession"] = {}
_lock = threading.Lock()


def state(driver: Driver, extra: dict | None = None) -> dict:
    try:
        url, title = driver.page.url, driver.page.title()
    except Exception:  # noqa: BLE001
        url, title = "", ""
    return {"url": url, "title": title, "screenshot": driver.screenshot_b64(), **VIEW, **(extra or {})}


def execute(driver: Driver, cmd: dict) -> dict:
    """One user gesture from the app, run on the driver's thread. Returns the new state."""
    kind = str(cmd.get("type", "state"))
    page = driver.page
    err = None
    try:
        if kind == "tap":
            page.mouse.click(float(cmd["x"]), float(cmd["y"]))
            driver._settle()
        elif kind == "type":
            page.keyboard.type(str(cmd.get("text", "")), delay=15)
            if cmd.get("submit"):
                page.keyboard.press("Enter")
                driver._settle()
        elif kind == "key":
            page.keyboard.press(str(cmd.get("key", "Enter")))
            driver._settle()
        elif kind == "scroll":
            page.mouse.wheel(0, float(cmd.get("dy", 600)))
            time.sleep(0.25)
        elif kind == "navigate":
            url = str(cmd.get("url", "")).strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            page.goto(url, wait_until="domcontentloaded")
        elif kind == "back":
            page.go_back(wait_until="domcontentloaded")
        elif kind == "forget":
            _forget_on(driver, str(cmd.get("domain", "")))
        elif kind == "cookies":
            return {"cookies": [{"domain": c.get("domain", ""), "expires": c.get("expires", -1)} for c in driver.ctx.cookies()]}
        elif kind == "read":
            # the agent reading a page: open it here so the user sees it, then hand back the readable text
            url = str(cmd.get("url", "")).strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            driver._settle()
            text = page.evaluate("() => (document.body && document.body.innerText) || ''")
            return state(driver, {"text": str(text)[:120000]})
        elif kind != "state":
            err = f"unknown input {kind!r}"
    except Exception as e:  # noqa: BLE001
        err = str(e).splitlines()[0][:200]
    return state(driver, {"error": err} if err else None)


def _forget_on(driver: Driver, domain: str):
    domain = domain.lstrip(".").lower()
    keep = [c for c in driver.ctx.cookies() if not (c.get("domain", "").lstrip(".").lower().endswith(domain))]
    driver.ctx.clear_cookies()
    if keep:
        driver.ctx.add_cookies(keep)


class LiveSession(threading.Thread):
    """A browser with no task: the user drives it from the phone (sign-ins, checks)."""

    def __init__(self, home: pathlib.Path):
        super().__init__(daemon=True, name="browser-live")
        self.home = home
        self.q: "queue.Queue[tuple[dict, queue.Queue]]" = queue.Queue()
        self.driver: Driver | None = None
        self.ready = threading.Event()
        self.error: str | None = None
        self.closed = False
        self.last_touch = time.time()

    def run(self):
        try:
            self.driver = Driver(self.home)
        except Exception as e:  # noqa: BLE001
            self.error = f"Could not start the browser: {e}"
            self.ready.set()
            return
        self.ready.set()
        try:
            while not self.closed:
                try:
                    cmd, reply = self.q.get(timeout=LIVE_IDLE_S)
                except queue.Empty:
                    break
                if cmd.get("type") == "close":
                    reply.put({"closed": True})
                    break
                self.last_touch = time.time()
                reply.put(execute(self.driver, cmd))
        finally:
            self.closed = True
            try:
                self.driver.close()
            except Exception:  # noqa: BLE001
                pass
            self.driver = None
            with _lock:
                if LIVE.get(str(self.home)) is self:
                    del LIVE[str(self.home)]

    def command(self, cmd: dict, timeout: float = 30) -> dict:
        if self.closed or self.driver is None:
            raise RuntimeError("the browser session is closed")
        reply: queue.Queue = queue.Queue()
        self.q.put((cmd, reply))
        return reply.get(timeout=timeout)

    def close(self):
        if not self.closed:
            try:
                self.command({"type": "close"}, timeout=10)
            except Exception:  # noqa: BLE001
                self.closed = True


def open_session(home: pathlib.Path) -> LiveSession:
    with _lock:
        s = LIVE.get(str(home))
        if s and not s.closed:
            return s
        s = LiveSession(home)
        LIVE[str(home)] = s
    s.start()
    s.ready.wait(timeout=60)
    if s.error:
        raise RuntimeError(s.error)
    return s


def current(home: pathlib.Path) -> LiveSession | None:
    s = LIVE.get(str(home))
    return s if s and not s.closed and s.driver is not None else None


def close_for(home: pathlib.Path):
    """Called before a task launches: only one Chromium may hold the profile."""
    s = LIVE.get(str(home))
    if s:
        s.close()
        s.join(timeout=15)


# ---------------------------------------------------------------- logins --
def _chrome_time(us: int | None) -> float | None:
    return (us / 1_000_000 - 11644473600) if us else None


def _sites_from(rows: list[tuple]) -> list[dict]:
    """rows of (host, count, last_access_ts_or_None, persistent) -> one entry per site, newest first."""
    by_site: dict[str, dict] = {}
    for host, n, last, persistent in rows:
        site = host.lstrip(".").lower()
        parts = site.split(".")
        site = ".".join(parts[-2:]) if len(parts) > 2 and parts[-2] not in ("co", "com", "org", "gov", "ac") else site
        cur = by_site.setdefault(site, {"site": site, "cookies": 0, "last_used_at": None, "persistent": False})
        cur["cookies"] += n
        if last and (cur["last_used_at"] is None or last > cur["last_used_at"]):
            cur["last_used_at"] = last
        cur["persistent"] = cur["persistent"] or bool(persistent)
    out = [x for x in by_site.values() if x["persistent"]]
    out.sort(key=lambda x: -(x["last_used_at"] or 0))
    return out[:100]


def logins(home: pathlib.Path, host=None) -> list[dict]:
    """Sites the profile holds cookies for. Through the open browser when there is one (cookies only
    reach the database on flush), else from a copy of the cookie DB without launching anything."""
    if host is not None:
        try:
            cookies = host.command({"type": "cookies"}, timeout=20).get("cookies", [])
            return _sites_from([(c["domain"], 1, time.time(), (c.get("expires") or -1) > 0) for c in cookies])
        except Exception:  # noqa: BLE001
            pass
    profile = home / ".browser" / "profile" / "Default"
    candidates = [c for c in (profile / "Network" / "Cookies", profile / "Cookies") if c.exists()]   # path differs by Chromium build
    if not candidates:
        return []
    db = max(candidates, key=lambda c: c.stat().st_mtime)
    tmp = pathlib.Path(tempfile.mkdtemp()) / "Cookies"
    try:
        shutil.copy2(db, tmp)
        con = sqlite3.connect(str(tmp))
        rows = con.execute("select host_key, count(*), max(last_access_utc), max(expires_utc) from cookies group by host_key").fetchall()
        con.close()
    except sqlite3.Error:
        return []
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return _sites_from([(host, n, _chrome_time(last), bool(exp and exp > 0)) for host, n, last, exp in rows])


def forget(home: pathlib.Path, domain: str, host=None) -> dict:
    """Drop a site's cookies through whichever host owns the profile, or a short-lived session."""
    if host is not None:
        return host.command({"type": "forget", "domain": domain})
    s = open_session(home)
    try:
        return s.command({"type": "forget", "domain": domain})
    finally:
        s.close()
