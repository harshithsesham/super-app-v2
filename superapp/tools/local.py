"""Real implementations of the local tools: shell, files, processes, todo.
Everything resolves relative to the agent's home directory.
"""
from __future__ import annotations
import json, os, pathlib, subprocess, threading, time, uuid
from .registry import REGISTRY, ToolError
from ..config import CONFIG, REPO


def _env() -> dict:
    """Shell commands see the agent's home as HOME so `~` means the same thing in
    every tool, and the repo's bin/ (connector CLIs like hatch_gws_cli) on PATH."""
    env = dict(os.environ)
    env["HOME"] = str(CONFIG.home)
    env["PATH"] = str(REPO / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _resolve(path: str) -> pathlib.Path:
    home = CONFIG.home
    if path == "~":
        return home
    if path.startswith("~/"):
        return home / path[2:]
    p = pathlib.Path(path)
    return p if p.is_absolute() else home / p


class Session:
    """A background command with captured output and a finish callback."""

    def __init__(self, command: str, workdir: str, timeout_s: int):
        self.id = f"sess_{uuid.uuid4().hex[:8]}"
        self.command, self.started, self.timeout_s = command, time.time(), timeout_s
        self.output: list[str] = []
        self.exit_code: int | None = None
        self.on_finish = None
        self.proc = subprocess.Popen(command, shell=True, cwd=workdir, text=True, env=_env(),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.output.append(line)
            if len(self.output) > 5000:
                del self.output[:1000]
        self.exit_code = self.proc.wait()
        if self.on_finish:
            self.on_finish(self)

    def _watchdog(self):
        while self.exit_code is None:
            if time.time() - self.started > self.timeout_s:
                self.proc.kill()
                return
            time.sleep(1)


SESSIONS: dict[str, Session] = {}


@REGISTRY.register("muse.exec")
def exec_(command: str, workdir: str | None = None, timeout_s: int | None = None,
          background: bool = False, _ctx: dict | None = None):
    wd = str(_resolve(workdir) if workdir else CONFIG.home)
    if background:
        s = Session(command, wd, timeout_s or 1800)
        SESSIONS[s.id] = s
        if _ctx and _ctx.get("on_background_finish"):
            s.on_finish = _ctx["on_background_finish"]
        return {"session_id": s.id, "status": "running",
                "note": "The result will be delivered to you automatically when it finishes."}
    try:
        p = subprocess.run(command, shell=True, cwd=wd, capture_output=True, text=True, timeout=timeout_s or 60,
                           env=_env())
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "output": "", "error": f"timed out after {timeout_s or 60}s; use background=true"}
    out = p.stdout + p.stderr
    return {"exit_code": p.returncode, "output": out[-12000:], "truncated": len(out) > 12000}


def _session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if not s:
        raise ToolError(f"no session {session_id}")
    return s


@REGISTRY.register("process.list")
def process_list():
    return {"sessions": [{"session_id": s.id, "command": s.command[:120],
                          "status": "running" if s.exit_code is None else "done", "exit_code": s.exit_code}
                         for s in SESSIONS.values()]}


@REGISTRY.register("process.log")
def process_log(session_id: str, tail: int = 200):
    s = _session(session_id)
    return {"session_id": s.id, "output": "".join(s.output[-tail:]), "exit_code": s.exit_code}


@REGISTRY.register("process.poll")
def process_poll(session_id: str):
    s = _session(session_id)
    return {"session_id": s.id, "finished": s.exit_code is not None, "exit_code": s.exit_code}


@REGISTRY.register("process.kill")
def process_kill(session_id: str):
    s = _session(session_id)
    s.proc.kill()
    return {"session_id": s.id, "killed": True}


@REGISTRY.register("process.write")
def process_write(session_id: str, data: str):
    s = _session(session_id)
    if s.exit_code is not None:
        raise ToolError(f"session {session_id} is not running")
    s.proc.stdin.write(data)
    s.proc.stdin.flush()
    return {"ok": True}


@REGISTRY.register("process.send_keys")
def process_send_keys(session_id: str, keys: list[str]):
    mapping = {"Enter": "\n", "C-c": "\x03", "C-d": "\x04", "Tab": "\t"}
    return process_write(session_id, "".join(mapping.get(k, k) for k in keys))


@REGISTRY.register("muse.read")
def read(path: str, offset: int = 1, limit: int = 200):
    p = _resolve(path)
    if not p.exists():
        raise ToolError(f"{path} does not exist")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"path": str(p), "from": offset, "lines": lines[offset - 1: offset - 1 + limit], "total_lines": len(lines)}


@REGISTRY.register("muse.write")
def write(path: str, content: str):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p), "bytes": len(content.encode())}


@REGISTRY.register("muse.edit")
def edit(path: str, old: str, new: str):
    p = _resolve(path)
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise ToolError(f"old string must appear exactly once, found {n}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return {"path": str(p), "ok": True}


def _todo_path() -> pathlib.Path:
    return CONFIG.home / ".todo.json"


@REGISTRY.register("todo.write")
def todo_write(items: list[dict]):
    for i, it in enumerate(items):
        it.setdefault("id", f"t{i + 1}")
    _todo_path().write_text(json.dumps(items, indent=1))
    return {"count": len(items)}


@REGISTRY.register("todo.read")
def todo_read():
    p = _todo_path()
    return {"items": json.loads(p.read_text()) if p.exists() else []}


@REGISTRY.register("tool_search.load_tool_namespace")
def load_tool_namespace(namespace: str):
    if namespace not in REGISTRY.namespaces:
        raise ToolError(f"unknown namespace {namespace}")
    REGISTRY.load_namespace(namespace)
    return {"loaded": namespace, "functions": REGISTRY.namespaces[namespace]["functions"]}
