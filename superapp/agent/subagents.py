"""Subagent tools: spawn / list / send / resume / close.

A child starts with no inherited transcript, runs in a worker thread under
the configured concurrency cap, and its final message is delivered to the
parent as a `[Subagent Report]` handoff. Children at depth >= 2 cannot spawn.
"""
from __future__ import annotations
import threading, time
from concurrent.futures import ThreadPoolExecutor
from ..config import CONFIG
from ..tools.registry import REGISTRY, ToolError
from .loop import Agent

POOL = ThreadPoolExecutor(max_workers=int(CONFIG.resources.get("max_concurrent_agents", 8)))
SPAWNS: dict[str, dict] = {}
_lock = threading.Lock()


def _run(spawn: dict, message: str):
    child: Agent = spawn["agent"]
    parent: Agent = spawn["parent"]
    spawn["status"] = "running"
    try:
        report = child.run_turn(message)
        spawn["status"] = "done" if not child.closed else "interrupted"
        spawn["final_response"] = report
    except Exception as e:  # noqa: BLE001
        spawn["status"] = "failed"
        spawn["final_response"] = f"{type(e).__name__}: {e}"
        report = f"(failed) {spawn['final_response']}"
    spawn["completed_at"] = time.time()
    parent.deliver(f"[Subagent Report] spawn_id={spawn['id']} label={spawn['label']} status={spawn['status']}\n{report}")


@REGISTRY.register("subagent.spawn")
def spawn(message: str | None = None, items: list | None = None, label: str | None = None,
          timeout_s: int = 1800, _ctx: dict | None = None):
    parent: Agent = _ctx["agent"]
    if parent.depth >= 2:
        raise ToolError("maximum subagent depth reached; do this work inline")
    brief = message or "\n".join(str(i.get("text", i)) for i in (items or []))
    if not brief.strip():
        raise ToolError("a subagent needs a full brief in `message`")
    child = Agent(role="subagent", depth=parent.depth + 1, llm=parent.llm, memory=parent.memory, tz=parent.tz,
                  label=label, on_event=parent.on_event, parent=parent)
    spawn_rec = {"id": f"spawn_{child.id[6:]}", "agent": child, "parent": parent, "label": label or brief[:40],
                 "status": "queued", "created_at": time.time(), "completed_at": None, "final_response": None,
                 "child_depth": child.depth, "prompt": brief}
    with _lock:
        SPAWNS[spawn_rec["id"]] = spawn_rec
    POOL.submit(_run, spawn_rec, f"[Subagent Task]\n{brief}")
    parent.on_event("subagent_spawn", {"spawn_id": spawn_rec["id"], "label": spawn_rec["label"]})
    return {"spawn_id": spawn_rec["id"], "status": "running",
            "note": "The report will be delivered to you automatically when it finishes; do not poll."}


def _get(spawn_id: str) -> dict:
    s = SPAWNS.get(spawn_id)
    if not s:
        raise ToolError(f"no subagent {spawn_id}")
    return s


@REGISTRY.register("subagent.list")
def list_(_ctx: dict | None = None):
    me = _ctx["agent"].id if _ctx else None
    return {"subagents": [{"spawn_id": s["id"], "label": s["label"], "status": s["status"], "depth": s["child_depth"]}
                          for s in SPAWNS.values() if me is None or s["parent"].id == me]}


@REGISTRY.register("subagent.send")
def send(spawn_id: str, message: str, interrupt: bool = False):
    s = _get(spawn_id)
    child: Agent = s["agent"]
    if s["status"] == "running":
        if interrupt:
            child.closed = True
            s["status"] = "interrupted"
        child.deliver(f"[Follow-up from parent]\n{message}")
        return {"spawn_id": spawn_id, "delivered": True, "status": s["status"]}
    child.closed = False
    POOL.submit(_run, s, f"[Follow-up from parent]\n{message}")
    return {"spawn_id": spawn_id, "delivered": True, "status": "running"}


@REGISTRY.register("subagent.resume")
def resume(spawn_id: str):
    s = _get(spawn_id)
    if s["status"] not in ("interrupted", "failed"):
        raise ToolError(f"subagent {spawn_id} is {s['status']}, nothing to resume")
    s["agent"].closed = False
    POOL.submit(_run, s, "[Resume] Continue the task from where you stopped and report back.")
    return {"spawn_id": spawn_id, "status": "running"}


@REGISTRY.register("subagent.close")
def close(spawn_id: str):
    s = _get(spawn_id)
    s["agent"].closed = True
    s["status"] = "closed"
    return {"spawn_id": spawn_id, "status": "closed"}
