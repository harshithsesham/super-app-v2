"""Browser tasks: a focused worker agent that drives Chromium for one job.

The parent agent calls `browser.spawn_task`; a TaskRunner thread owns the
Playwright driver and a worker Agent in the `browser_task` role whose only
tools are `muse.automation` and `muse.browser_hand_off`. Every automation
call emits a `browser_step` event with a screenshot so the app can show the
live Browser card. The worker ends with a hand-off whose outcome
(completed, ask_for_information, failed) is delivered to the parent as a
report; `browser.steer_task` resumes a parked task with the parent's answer.
"""
from __future__ import annotations
import queue, re, threading, time, uuid
from datetime import datetime, timezone
from ..prompts import assembler
from ..tools.registry import REGISTRY, ToolError
from ..agent.loop import Agent
from .driver import Driver
from . import live

TASKS: dict[str, "TaskRunner"] = {}
_lock = threading.Lock()
IDLE_CLOSE_S = 900
SENSITIVE = re.compile(r"checkout|payment|place order|pay now|purchase|buy now|confirm order|submit order|complete purchase", re.I)


class TaskRunner(threading.Thread):
    def __init__(self, parent: Agent, instruction: str, start_url: str | None, title: str | None, allow_credentials: bool):
        super().__init__(daemon=True)
        self.id = f"btask_{uuid.uuid4().hex[:10]}"
        self.parent = parent
        self.instruction, self.start_url = instruction, start_url
        self.title = title or (instruction.strip().split("\n")[0][:60])
        self.allow_credentials = allow_credentials
        self.status = "queued"          # queued | running | needs_user | completed | failed | stopped
        self.status_title = "Starting…"
        self.url = ""
        self.screenshot = ""
        self.report: str | None = None
        self.question: str | None = None
        self.step_count = 0
        self.created_at, self.updated_at = time.time(), time.time()
        self.q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.driver: Driver | None = None
        self.pause_requested = False    # the user asked to take over mid-run
        self.last_touch = time.time()   # last user gesture while in control; keeps the browser open
        self.agent = Agent("browser_task", depth=parent.depth + 1, llm=parent.llm, memory=parent.memory, tz=parent.tz,
                           label=self.title, on_event=parent.on_event, parent=parent)
        self.agent.only_tools = {"muse.automation", "muse.browser_hand_off", "muse.visual_automation"}
        self.agent.browser_task = self  # type: ignore[attr-defined]
        self.agent.approvals = getattr(parent, "approvals", None)
        self.agent.store = getattr(parent, "store", None)

    # ------------------------------------------------------------- public --
    def public(self) -> dict:
        return {"task_id": self.id, "title": self.title, "status": self.status, "status_title": self.status_title,
                "url": self.url, "step_count": self.step_count, "question": self.question,
                "created_at": self.created_at, "updated_at": self.updated_at}

    def emit(self, with_shot: bool = True):
        self.updated_at = time.time()
        if with_shot and self.driver:
            self.screenshot = self.driver.screenshot_b64()
            self.url = self.driver.page.url
        self.parent.on_event("browser_step", {"task_id": self.id, "title": self.title, "status": self.status,
                                              "status_title": self.status_title, "url": self.url,
                                              "screenshot": self.screenshot})
        if self.parent.store is not None:
            terminal = self.status in ("completed", "failed", "stopped")
            try:
                self.parent.store.upsert_browser_task({
                    "task_id": self.id, "owner_agent_id": self.parent.id, "parent_agent_id": self.parent.id, "status": self.status,
                    "title": self.title, "step_count": self.step_count, "initial_instruction": self.instruction[:20000],
                    "outcome_status": self.status if terminal or self.status == "needs_user" else None,
                    "outcome_reason": self.report if terminal else None,
                    "terminal_reason": {"completed": "browser_agent_completed", "failed": "browser_agent_reported_failure",
                                        "stopped": "user_stop"}.get(self.status),
                    "completed_at": datetime.now(timezone.utc) if terminal else None,
                    "outcome_at": datetime.now(timezone.utc) if terminal or self.status == "needs_user" else None})
            except Exception as e:  # noqa: BLE001
                self.parent.on_event("store_error", {"agent": self.parent.id, "error": f"{type(e).__name__}: {e}"})

    # --------------------------------------------------------------- run ---
    def run(self):
        try:
            self.driver = Driver(self.parent.memory.home)
        except Exception as e:  # noqa: BLE001
            self.status, self.report = "failed", f"Could not start the browser: {e}"
            self.emit(False)
            self.parent.deliver(f"[Browser Task Report] task_id={self.id} outcome=failed\n{self.report}")
            return
        first = (f"[Subagent Task]\n{self.instruction}\n" + (f"Start URL: {self.start_url}\n" if self.start_url else "")
                 + f"Now: {assembler.time_lines(self.parent.tz)['time_tag']}")
        self.q.put(("run", first))
        try:
            while True:
                try:
                    kind, payload = self.q.get(timeout=60)
                except queue.Empty:
                    # keep the browser while the worker is running or the user is (or may be) in control
                    if self.status == "running" or (self.status == "needs_user" and time.time() - self.last_touch < IDLE_CLOSE_S):
                        continue
                    break
                if kind == "close":
                    break
                if kind == "cmd":   # a gesture from the app while the user is in control
                    cmd, reply = payload  # type: ignore[misc]
                    self.last_touch = time.time()
                    try:
                        reply.put(live.execute(self.driver, cmd))
                    except Exception as e:  # noqa: BLE001
                        reply.put({"error": str(e)})
                    continue
                self.status, self.status_title = "running", "Working…"
                self.emit(False)
                self.agent.handoff = None  # type: ignore[attr-defined]
                try:
                    text = self.agent.run_turn(payload)
                except Exception as e:  # noqa: BLE001
                    self.status, self.report = "failed", f"Browser worker error: {type(e).__name__}: {e}"
                    self.parent.deliver(f"[Browser Task Report] task_id={self.id} outcome=failed\n{self.report}")
                    self.emit(False)
                    continue
                if self.pause_requested:
                    # the user took over: hold the page, no report; handback() resumes the worker
                    self.pause_requested = False
                    self.agent.closed = False
                    self.status, self.status_title = "needs_user", "You're in control"
                    self.question = None
                    self.last_touch = time.time()
                    self.emit(True)
                    continue
                self._finish(text)
                if self.status in ("completed", "failed", "stopped"):
                    break
        finally:
            try:
                self.driver.close()
            except Exception:  # noqa: BLE001
                pass
            self.driver = None

    def _finish(self, text: str):
        ho = getattr(self.agent, "handoff", None)
        if not ho:
            ho = {"outcome": "completed", "report": text or "(no report)"}
        outcome = ho.get("outcome", "completed")
        self.report = ho.get("report", "")
        if outcome == "ask_for_information":
            self.status, self.status_title = "needs_user", "Needs your answer"
            self.question = ho.get("question") or self.report
            self.last_touch = time.time()
        elif outcome == "failed":
            self.status, self.status_title = "failed", "Could not finish"
        else:
            self.status, self.status_title = "completed", "Done"
        self.emit(True)
        self.parent.deliver(f"[Browser Task Report] task_id={self.id} outcome={outcome} title={self.title}\n{self.report}"
                            + (f"\nQuestion for the user: {self.question}" if self.question else ""))

    # ----------------------------------------------------------- control ---
    def steer(self, instruction: str):
        if self.status in ("completed", "failed", "stopped"):
            raise ToolError(f"task {self.id} is {self.status}; spawn a new task")
        self.q.put(("run", f"[Follow-up from parent]\n{instruction}\nNow: {assembler.time_lines(self.parent.tz)['time_tag']}"))

    def stop(self):
        self.status, self.status_title = "stopped", "Stopped"
        self.agent.closed = True
        self.q.put(("close", ""))
        self.emit(False)

    # ------------------------------------------------------- live control ---
    def command(self, cmd: dict, timeout: float = 30) -> dict:
        """A gesture from the app. Only served between worker turns: take over first while it is running."""
        if self.driver is None or self.status in ("completed", "failed", "stopped"):
            raise RuntimeError("this task's browser is closed")
        reply: queue.Queue = queue.Queue()
        self.q.put(("cmd", (cmd, reply)))
        return reply.get(timeout=timeout)

    def takeover(self):
        """Pause the worker after its current step and give the page to the user."""
        if self.status == "running":
            self.pause_requested = True
            self.agent.closed = True   # the loop returns at the next round; run() turns that into needs_user
        elif self.status == "needs_user":
            self.status_title = "You're in control"
            self.last_touch = time.time()
            self.emit(False)
        else:
            raise RuntimeError(f"task is {self.status}")

    def handback(self, note: str = ""):
        if self.status != "needs_user":
            raise RuntimeError(f"task is {self.status}, not waiting on you")
        self.q.put(("run", "[The user took control of the browser and has handed it back]\n"
                    + (f"Their note: {note.strip()}\n" if note.strip() else "")
                    + "The page may have changed under you: take a fresh snapshot before acting, then continue the task.\n"
                    f"Now: {assembler.time_lines(self.parent.tz)['time_tag']}"))


# ---------------------------------------------------------- parent tools ---
@REGISTRY.register("browser.spawn_task")
def spawn_task(instruction: str, start_url: str | None = None, title: str | None = None,
               allow_credentials: bool = False, _ctx: dict | None = None):
    parent: Agent = _ctx["agent"]
    if parent.role != "chat":
        raise ToolError("only the main agent can operate the browser")
    live.close_for(parent.memory.home)   # one Chromium per profile: a free session yields to the task
    t = TaskRunner(parent, instruction, start_url, title, allow_credentials)
    with _lock:
        TASKS[t.id] = t
    t.start()
    parent.on_event("browser_task_spawn", {"task_id": t.id, "title": t.title})
    return {"task_id": t.id, "status": "accepted", "title": t.title,
            "note": "The browser worker is running. Its report will be delivered to you automatically; do not poll."}


def _task(task_id: str) -> TaskRunner:
    t = TASKS.get(task_id)
    if not t:
        raise ToolError(f"no browser task {task_id}")
    return t


@REGISTRY.register("browser.steer_task")
def steer_task(task_id: str, instruction: str):
    _task(task_id).steer(instruction)
    return {"task_id": task_id, "status": "running", "note": "Delivered; the worker continues and will report back."}


@REGISTRY.register("browser.list_tasks")
def list_tasks(_ctx: dict | None = None):
    me = _ctx["agent"].id if _ctx else None
    return {"tasks": [t.public() for t in TASKS.values() if me is None or t.parent.id == me]}


@REGISTRY.register("browser.stop_task")
def stop_task(task_id: str):
    _task(task_id).stop()
    return {"task_id": task_id, "status": "stopped"}


# ---------------------------------------------------------- worker tools ---
def _runner(ctx: dict | None) -> TaskRunner:
    t = getattr(ctx["agent"], "browser_task", None) if ctx else None
    if not t or not t.driver:
        raise ToolError("no browser attached to this agent")
    return t


@REGISTRY.register("muse.automation")
def automation(actions: list[dict], _ctx: dict | None = None):
    t = _runner(_ctx)
    d = t.driver
    receipts, blocked = [], False
    for a in actions or []:
        if blocked:
            receipts.append({"action": a.get("action"), "dispatch": "not_started", "actionability_reason": "skipped after an earlier failure"})
            continue
        kind = str(a.get("action", ""))
        # purchases and submissions on payment pages stop at an approval card
        if kind in ("click", "type", "press") and _looks_sensitive(d, a):
            decision = _approve(t, a)
            if decision != "allow":
                receipts.append({"action": kind, "dispatch": "not_started",
                                 "actionability_reason": f"approval {decision}: the user did not approve this step; do not retry it"})
                blocked = True
                continue
        r = d.act(a)
        receipts.append(r.public())
        t.step_count += 1
        if r.dispatch != "done":
            blocked = True
        if a.get("status_title"):
            t.status_title = str(a["status_title"])[:40]
    obs = d.snapshot()
    t.status_title = _status_from(actions) or t.status_title
    t.emit(True)
    return {"receipts": receipts, "observation": obs}


def _status_from(actions: list[dict]) -> str | None:
    for a in reversed(actions or []):
        if a.get("status_title"):
            return str(a["status_title"])[:40]
    return None


def _looks_sensitive(d: Driver, a: dict) -> bool:
    try:
        url = d.page.url
        name = ""
        if a.get("ref"):
            loc = d.page.locator(f'[data-muse-ref="{a["ref"]}"]')
            if loc.count():
                name = (loc.first.inner_text(timeout=1000) or "")[:80]
        return bool(SENSITIVE.search(name)) or (bool(SENSITIVE.search(url)) and a.get("action") in ("press",) )
    except Exception:  # noqa: BLE001
        return False


def _approve(t: TaskRunner, a: dict) -> str:
    store = getattr(t.agent, "approvals", None)
    if store is None:
        return "unavailable"
    return store.request("browser_action", f"Browser · {t.title}",
                         "The browser task wants to take a step that may place an order or submit a payment.",
                         [{"label": "Page", "value": t.driver.page.url[:120]}, {"label": "Action", "value": f"{a.get('action')} {a.get('ref', '')} {str(a.get('text', ''))[:80]}".strip()}])


@REGISTRY.register("muse.visual_automation")
def visual_automation(**kw):
    raise ToolError("cursor gestures are not available in this build; use muse.automation with element refs")


@REGISTRY.register("muse.browser_hand_off")
def hand_off(outcome: str, report: str, question: str | None = None, _ctx: dict | None = None):
    agent = _ctx["agent"]
    if outcome not in ("completed", "ask_for_information", "failed"):
        raise ToolError("outcome must be completed, ask_for_information, or failed")
    agent.handoff = {"outcome": outcome, "report": report, "question": question}  # type: ignore[attr-defined]
    agent.stop_after_tools = True  # type: ignore[attr-defined]
    return {"status": "ok", "note": "Hand-off recorded. The task run ends now."}
