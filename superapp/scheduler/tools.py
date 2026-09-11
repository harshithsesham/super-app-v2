"""cron.* and hooks.* tool handlers, backed by the user's scheduler Engine
(attached to the main agent by the daemon as `agent.scheduler`)."""
from __future__ import annotations
import functools
from ..tools.registry import REGISTRY, ToolError
from .engine import Engine, ScheduleError


def _engine(ctx: dict | None) -> Engine:
    agent = ctx["agent"] if ctx else None
    eng = getattr(agent, "scheduler", None) or getattr(getattr(agent, "parent", None), "scheduler", None)
    if not eng:
        raise ToolError("the scheduler is not available in this session")
    return eng


def _wrap(fn):
    @functools.wraps(fn)  # keep the signature so the registry still passes _ctx
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except ScheduleError as e:
            raise ToolError(str(e))
    return inner


@REGISTRY.register("cron.add")
@_wrap
def cron_add(id: str, schedule: dict, enabled: bool = True, mode: str = "task", title: str | None = None, body: str | None = None,
             owner: str | None = None, delivery: list | None = None, retry: dict | None = None, _ctx: dict | None = None):
    eng = _engine(_ctx)
    v = eng.add({"id": id, "schedule": schedule, "enabled": enabled, "title": title, "body": body, "owner": owner, "delivery": delivery, "retry": retry})
    return {"ok": True, "job": v, "next_run_local": v.get("next_run_local"), "next_run_in": v.get("next_run_in"),
            "timezone_used": v["schedule"].get("timezone")}


@REGISTRY.register("cron.update")
@_wrap
def cron_update(id: str, schedule: dict | None = None, enabled: bool | None = None, mode: str | None = None, title: str | None = None,
                body: str | None = None, owner: str | None = None, delivery: list | None = None, retry: dict | None = None, _ctx: dict | None = None):
    v = _engine(_ctx).update({"id": id, "schedule": schedule, "enabled": enabled, "title": title, "body": body, "owner": owner, "delivery": delivery, "retry": retry})
    return {"ok": True, "job": v, "next_run_local": v.get("next_run_local"), "next_run_in": v.get("next_run_in")}


@REGISTRY.register("cron.remove")
@_wrap
def cron_remove(id: str, _ctx: dict | None = None):
    return _engine(_ctx).remove(id)


@REGISTRY.register("cron.view")
@_wrap
def cron_view(id: str, _ctx: dict | None = None):
    return _engine(_ctx).view(id)


@REGISTRY.register("cron.list")
@_wrap
def cron_list(include_disabled: bool = False, _ctx: dict | None = None):
    jobs = _engine(_ctx).list(include_disabled)
    return {"jobs": [{"id": j["id"], "title": j.get("title"), "enabled": j["enabled"], "schedule": j["schedule"], "owner": j.get("owner"),
                      "system": j["system"], "next_run_local": j.get("next_run_local"), "last_status": j.get("last_status")} for j in jobs]}


@REGISTRY.register("cron.status")
@_wrap
def cron_status(id: str | None = None, _ctx: dict | None = None):
    return _engine(_ctx).status(id)


@REGISTRY.register("cron.runs")
@_wrap
def cron_runs(id: str | None = None, limit: int = 20, _ctx: dict | None = None):
    eng = _engine(_ctx)
    return {"runs": eng.store.runs(id, int(limit)) if eng.store else []}


@REGISTRY.register("cron.run")
@_wrap
def cron_run(id: str, reason: str = "", _ctx: dict | None = None):
    return _engine(_ctx).run_now(id, reason)


@REGISTRY.register("hooks.add")
@_wrap
def hooks_add(id: str, script_path: str, prompt: str, poll_interval_secs: int = 60, script_timeout_secs: int = 600,
              delivery: list | None = None, _ctx: dict | None = None):
    h = _engine(_ctx).hook_add({"id": id, "script_path": script_path, "prompt": prompt, "poll_interval_secs": poll_interval_secs,
                                "script_timeout_secs": script_timeout_secs, "delivery": delivery})
    return {"ok": True, "hook": h, "note": "The hook starts disabled. Test it with hooks.dry_run, then hooks.enable."}


@REGISTRY.register("hooks.update")
@_wrap
def hooks_update(id: str, script_path: str | None = None, prompt: str | None = None, poll_interval_secs: int | None = None,
                 script_timeout_secs: int | None = None, delivery: list | None = None, _ctx: dict | None = None):
    spec = {k: v for k, v in {"id": id, "script_path": script_path, "prompt": prompt, "poll_interval_secs": poll_interval_secs,
                              "script_timeout_secs": script_timeout_secs, "delivery": delivery}.items() if v is not None}
    return {"ok": True, "hook": _engine(_ctx).hook_add(spec, update=True)}


@REGISTRY.register("hooks.remove")
@_wrap
def hooks_remove(id: str, _ctx: dict | None = None):
    return _engine(_ctx).hook_remove(id)


@REGISTRY.register("hooks.enable")
@_wrap
def hooks_enable(id: str, _ctx: dict | None = None):
    return {"ok": True, "hook": _engine(_ctx).hook_set_enabled(id, True)}


@REGISTRY.register("hooks.disable")
@_wrap
def hooks_disable(id: str, _ctx: dict | None = None):
    return {"ok": True, "hook": _engine(_ctx).hook_set_enabled(id, False)}


@REGISTRY.register("hooks.list")
@_wrap
def hooks_list(include_disabled: bool = False, _ctx: dict | None = None):
    eng = _engine(_ctx)
    return {"hooks": [h for h in eng.hooks.values() if include_disabled or h.get("enabled")]}


@REGISTRY.register("hooks.view")
@_wrap
def hooks_view(id: str, _ctx: dict | None = None):
    eng = _engine(_ctx)
    if id not in eng.hooks:
        raise ToolError(f"no hook {id}")
    return eng.hooks[id]


@REGISTRY.register("hooks.logs")
@_wrap
def hooks_logs(id: str, limit: int = 50, _ctx: dict | None = None):
    return {"entries": _engine(_ctx).hook_logs(id, int(limit))}


@REGISTRY.register("hooks.dry_run")
@_wrap
def hooks_dry_run(id: str, _ctx: dict | None = None):
    eng = _engine(_ctx)
    if id not in eng.hooks:
        raise ToolError(f"no hook {id}")
    return eng._poll_hook(eng.hooks[id], dry_run=True)


@REGISTRY.register("hooks.run")
@_wrap
def hooks_run(id: str, _ctx: dict | None = None):
    eng = _engine(_ctx)
    if id not in eng.hooks:
        raise ToolError(f"no hook {id}")
    return eng._poll_hook(eng.hooks[id], dry_run=False)


@REGISTRY.register("muse.nothing_to_do")
def nothing_to_do(reason: str | None = None, _ctx: dict | None = None):
    """End the turn with no visible message (used after a handoff that is not worth surfacing)."""
    agent = _ctx["agent"] if _ctx else None
    if agent is not None:
        agent.stop_after_tools = True
        agent.silent_turn = True
    return {"status": "ok", "note": "Turn ends silently."}
