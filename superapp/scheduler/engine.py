"""The scheduler: cron jobs and event hooks for one user, ticking once a second.

Jobs live as markdown definitions under ~/workspace/cron.d/<tier>/<id>.md
(frontmatter + body), mirrored into scheduler.jobs / job_definitions, with
every run in scheduler.job_runs. A due job is claimed by inserting its run
row (unique on job + scheduled time, so a restart cannot double-fire), then
executed by a scheduler_worker agent whose result is delivered to the main
agent as a handoff. The main agent decides whether the user hears about it.

Hooks pair a polling script under ~/hooks/scripts with a worker prompt. The
engine runs the script on its interval in the agent's shell environment;
a `wake` verdict starts an event_hook worker whose summary is delivered the
same way. Verdicts are appended to ~/hooks/logs/<id>.jsonl.

Two system jobs are ensured per user: memory-upkeep (hourly) and
morning-brief (daily). They show in cron.list as runtime-managed.
"""
from __future__ import annotations
import json, os, pathlib, re, subprocess, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from croniter import croniter
from ..config import CONFIG, REPO
from ..prompts import assembler

TIERS = {"minutely": "minutely", "hourly": "hourly", "daily": "daily", "weekly": "weekly", "monthly": "monthly",
         "yearly": "yearly", "interval": "hourly", "runonce": "daily"}
DOW = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
JOB_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ScheduleError(ValueError):
    pass


def cron_expr(schedule: dict) -> str:
    """Muse's schedule object -> a 5-field cron expression (runonce/interval handled by the engine)."""
    kind = schedule.get("kind")
    t = schedule.get("time", "09:00")
    if not re.fullmatch(r"\d{2}:\d{2}", str(t)):
        raise ScheduleError("time must be HH:MM")
    hh, mm = t.split(":")
    if kind == "daily":
        return f"{int(mm)} {int(hh)} * * *"
    if kind == "weekly":
        days = [DOW[d[:3].lower()] for d in schedule.get("dow", [])]
        if not days:
            raise ScheduleError("weekly needs dow")
        return f"{int(mm)} {int(hh)} * * {','.join(str(d) for d in sorted(days))}"
    if kind == "monthly":
        dom = schedule.get("dom") or []
        if not dom:
            raise ScheduleError("monthly needs dom")
        return f"{int(mm)} {int(hh)} {','.join(str(int(d)) for d in dom)} * *"
    if kind == "yearly":
        dom, month = schedule.get("dom") or [], schedule.get("month") or []
        if not dom or not month:
            raise ScheduleError("yearly needs dom and month")
        return f"{int(mm)} {int(hh)} {','.join(str(int(d)) for d in dom)} {','.join(str(int(m)) for m in month)} *"
    if kind == "interval":
        every = int(schedule.get("every", 3600))
        if every < 60:
            raise ScheduleError("interval must be at least 60 seconds")
        return f"@every {every}"
    if kind == "runonce":
        if not schedule.get("at"):
            raise ScheduleError("runonce needs at")
        return f"@at {schedule['at']}"
    raise ScheduleError(f"unknown schedule kind {kind!r}")


def next_run_utc(job: dict, after: float | None = None) -> int | None:
    sched, tz = job["schedule"], ZoneInfo(job["schedule"].get("timezone", "UTC"))
    base = datetime.fromtimestamp(after or time.time(), tz)
    expr = job["cron_expr"]
    if expr.startswith("@at "):
        at = datetime.fromisoformat(expr[4:]).replace(tzinfo=tz)
        return int(at.timestamp())
    if expr.startswith("@every "):
        every = int(expr[7:])
        anchor = datetime.fromisoformat(sched["at"]).replace(tzinfo=tz).timestamp() if sched.get("at") else job.get("created_at", time.time())
        n = max(0, int((base.timestamp() - anchor) // every) + 1)
        return int(anchor + n * every)
    return int(croniter(expr, base).get_next(datetime).timestamp())


def tier_for(schedule: dict) -> str:
    return TIERS.get(schedule.get("kind", "daily"), "daily")


class Engine:
    def __init__(self, room):
        self.room = room
        self.home: pathlib.Path = room.home
        self.store = room.store
        self.jobs: dict[str, dict] = {}
        self.hooks: dict[str, dict] = {}
        self.hook_next: dict[str, float] = {}
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.running: set[str] = set()
        self.last_user_activity = time.time()   # updated by the room on every user turn; gates the system jobs
        self._stop = threading.Event()
        self._lock = threading.Lock()
        (self.home / "workspace/cron.d").mkdir(parents=True, exist_ok=True)
        for d in ("scripts", "state", "logs", "definitions"):
            (self.home / "hooks" / d).mkdir(parents=True, exist_ok=True)
        self._load()
        self._ensure_system_jobs()
        threading.Thread(target=self._tick, daemon=True, name=f"scheduler-{room.user}").start()

    # ------------------------------------------------------------ loading --
    def _load(self):
        if self.store:
            for j in self.store.load_jobs():
                self.jobs[j["id"]] = j
        for p in (self.home / "workspace/cron.d").rglob("*.md"):
            j = self._read_job_file(p)
            if j and j["id"] not in self.jobs:
                j["next_run_at_utc"] = next_run_utc(j)
                self.jobs[j["id"]] = j
                if self.store:
                    self.store.upsert_job(j)
        for p in (self.home / "hooks/definitions").glob("*.json"):
            try:
                h = json.loads(p.read_text())
                self.hooks[h["id"]] = h
            except (json.JSONDecodeError, KeyError):
                continue

    def _read_job_file(self, p: pathlib.Path) -> dict | None:
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
        if not m:
            return None
        try:
            fm = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        fm["body"] = m.group(2).strip()
        fm["source_path"] = str(p)
        return fm

    def _write_job_file(self, job: dict) -> str:
        tier = tier_for(job["schedule"])
        owner = job.get("owner") or ""
        if owner.startswith("goal:"):
            d = self.home / "workspace/goals" / owner[5:] / "crons" / tier
        else:
            d = self.home / "workspace/cron.d" / tier
        d.mkdir(parents=True, exist_ok=True)
        # old file in another tier goes away
        for old in (self.home / "workspace").rglob(f"{job['id']}.md"):
            if "cron" in old.as_posix():
                old.unlink(missing_ok=True)
        p = d / f"{job['id']}.md"
        fm = {k: v for k, v in job.items() if k not in ("body", "source_path", "next_run_at_utc", "last_run_at_utc", "last_status", "consecutive_failures")}
        p.write_text("---\n" + json.dumps(fm, indent=1, default=str) + "\n---\n" + (job.get("body") or "") + "\n", encoding="utf-8")
        return str(p)

    def _ensure_system_jobs(self):
        tz = self.room.agent.tz
        system = {
            "memory-upkeep": {"title": "Memory upkeep", "schedule": {"kind": "interval", "every": 3600, "timezone": tz},
                              "role": "memory_flush", "body": (
                                  "Consolidate what happened recently into durable memory. Read ~/MEMORY.md, today's and yesterday's daily logs under ~/memory/, "
                                  "and the recent conversation excerpt in this task. Update ~/MEMORY.md in place with muse.edit or muse.write: durable facts, "
                                  "preferences, commitments, and ongoing items, newest claims superseding older ones (fix the entry, do not append duplicates). "
                                  "Then refresh the four bank files under ~/memory/bank/: experience.md (one-line episodic entries with `(src: memory/<date>.md:<line>)`), "
                                  "opinions.md, reflections.md (patterns about the user and how to work with them), world.md (background facts). "
                                  "Keep people pages under ~/memory/people/ current. Never record secrets. Finish with a two-line summary of what changed.")},
            "morning-brief": {"title": "Morning brief", "schedule": {"kind": "daily", "time": "07:00", "timezone": tz},
                              "role": "scheduler_worker", "body": (
                                  "Write today's brief for the user: what is on their plate today from memory, goals, and any connected services you can read "
                                  "(use the gmail skill only if Gmail is connected), plus one useful thing you noticed. Keep it under 120 words, in the assistant's voice. "
                                  "Save it by prepending a post to ~/workspace/feed.json: a JSON array of objects with id, kicker ('Brief'), category ('Today'), title, body, ts (unix seconds). "
                                  "Then finish with the brief text as your result summary.")},
        }
        for jid, spec in system.items():
            if jid in self.jobs:
                continue
            job = {"id": jid, "system": True, "mode": "task", "enabled": True, "created_at": time.time(), **spec}
            job["cron_expr"] = cron_expr(job["schedule"])
            job["next_run_at_utc"] = next_run_utc(job)
            self.jobs[jid] = job
            if self.store:
                self.store.upsert_job(job)

    # -------------------------------------------------------------- tools --
    def add(self, spec: dict) -> dict:
        jid = spec.get("id", "")
        if not JOB_ID.match(jid):
            raise ScheduleError("id must be short kebab-case, e.g. weekly-energy-check-in")
        if jid in self.jobs and self.jobs[jid].get("system"):
            raise ScheduleError(f"{jid} is a runtime-managed system job")
        sched = dict(spec.get("schedule") or {})
        sched.setdefault("timezone", self.room.agent.tz)
        job = {"id": jid, "title": spec.get("title") or jid, "mode": "task", "enabled": bool(spec.get("enabled", True)),
               "schedule": sched, "body": spec.get("body") or "", "owner": spec.get("owner"), "delivery": spec.get("delivery") or [{"surface": "main"}],
               "retry": {"max_retries": int((spec.get("retry") or {}).get("max_retries", 0)), "on_failure": bool((spec.get("retry") or {}).get("on_failure", False))},
               "created_at": time.time()}
        job["cron_expr"] = cron_expr(sched)
        job["next_run_at_utc"] = next_run_utc(job)
        job["source_path"] = self._write_job_file(job)
        with self._lock:
            self.jobs[jid] = job
        if self.store:
            self.store.upsert_job(job)
        return self.view(jid)

    def update(self, spec: dict) -> dict:
        jid = spec.get("id", "")
        job = self.jobs.get(jid)
        if not job:
            raise ScheduleError(f"no job {jid}")
        if job.get("system"):
            raise ScheduleError(f"{jid} is a runtime-managed system job")
        for k in ("title", "body", "owner", "delivery", "enabled"):
            if k in spec and spec[k] is not None:
                job[k] = spec[k]
        if spec.get("retry"):
            job["retry"] = {**job.get("retry", {}), **spec["retry"]}
        if spec.get("schedule"):
            job["schedule"] = {**job["schedule"], **spec["schedule"]}
            job["cron_expr"] = cron_expr(job["schedule"])
        job["next_run_at_utc"] = next_run_utc(job)
        job["source_path"] = self._write_job_file(job)
        if self.store:
            self.store.upsert_job(job)
        return self.view(jid)

    def remove(self, jid: str) -> dict:
        job = self.jobs.get(jid)
        if not job:
            raise ScheduleError(f"no job {jid}")
        if job.get("system"):
            raise ScheduleError(f"{jid} is a runtime-managed system job")
        with self._lock:
            self.jobs.pop(jid, None)
        if job.get("source_path"):
            pathlib.Path(job["source_path"]).unlink(missing_ok=True)
        if self.store:
            self.store.delete_job(jid)
        return {"id": jid, "removed": True}

    def view(self, jid: str) -> dict:
        job = self.jobs.get(jid)
        if not job:
            raise ScheduleError(f"no job {jid}")
        tz = ZoneInfo(job["schedule"].get("timezone", "UTC"))
        nxt = job.get("next_run_at_utc")
        out = {k: v for k, v in job.items() if k not in ("source_path",)}
        if nxt:
            dt = datetime.fromtimestamp(nxt, tz)
            secs = max(0, int(nxt - time.time()))
            out["next_run_local"] = dt.strftime("%a %Y-%m-%d %H:%M %Z")
            out["next_run_in"] = f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{secs // 60}m"
        out["system"] = bool(job.get("system"))
        return out

    def next_due(self) -> dict:
        """Earliest enabled job and whether any hook is polling; the cell's idle-exit and the gateway's wake use it."""
        with self._lock:
            times = [j["next_run_at_utc"] for j in self.jobs.values() if j.get("enabled", True) and j.get("next_run_at_utc")]
            hooks_active = any(h.get("enabled") for h in self.hooks.values())
        return {"next_due_utc": min(times) if times else None, "hooks_active": hooks_active,
                "running_jobs": sorted(self.running)}

    def list(self, include_disabled: bool = False) -> list[dict]:
        return [self.view(j) for j in sorted(self.jobs) if include_disabled or self.jobs[j].get("enabled", True)]

    def status(self, jid: str | None = None) -> dict:
        counts = self.store.run_counts(jid) if self.store else {"queued": 0, "running": len(self.running)}
        if jid:
            v = self.view(jid)
            return {"id": jid, "enabled": v["enabled"], "schedule": v["schedule"], "last_run_at_utc": v.get("last_run_at_utc"),
                    "last_status": v.get("last_status"), "next_run_local": v.get("next_run_local"), "next_run_in": v.get("next_run_in"), **counts}
        return {"enabled_jobs": sum(1 for j in self.jobs.values() if j.get("enabled", True)), "total_jobs": len(self.jobs), **counts}

    def run_now(self, jid: str, reason: str = "manual") -> dict:
        job = self.jobs.get(jid)
        if not job:
            raise ScheduleError(f"no job {jid}")
        self.pool.submit(self._execute, job, int(time.time()), f"manual: {reason}"[:200])
        return {"id": jid, "status": "queued", "note": "The run's result will be delivered to you when it finishes."}

    # --------------------------------------------------------------- tick --
    def _tick(self):
        while not self._stop.is_set():
            now = time.time()
            try:
                with self._lock:
                    due = [j for j in self.jobs.values() if j.get("enabled", True) and j.get("next_run_at_utc") and j["next_run_at_utc"] <= now
                           and j["id"] not in self.running]
                for job in due:
                    scheduled = int(job["next_run_at_utc"])
                    if job["cron_expr"].startswith("@at "):
                        job["enabled"] = False
                        job["next_run_at_utc"] = None
                    else:
                        job["next_run_at_utc"] = next_run_utc(job, after=scheduled + 1)
                    if self.store:
                        self.store.upsert_job(job)
                    why = self._should_skip(job, now)
                    if why:
                        self.room.on_event("scheduled_skip", {"job_id": job["id"], "title": job.get("title", job["id"]), "reason": why})
                        continue
                    self.pool.submit(self._execute, job, scheduled, "schedule")
                for h in list(self.hooks.values()):
                    if not h.get("enabled"):
                        continue
                    if self.hook_next.get(h["id"], 0) <= now:
                        self.hook_next[h["id"]] = now + int(h.get("poll_interval_secs", 60))
                        self.pool.submit(self._poll_hook, h, False)
            except Exception as e:  # noqa: BLE001
                self.room.on_event("scheduler_error", {"error": f"{type(e).__name__}: {e}"})
            self._stop.wait(1.0)

    def note_activity(self):
        self.last_user_activity = time.time()

    def _should_skip(self, job: dict, now: float) -> str | None:
        """System jobs cost model calls; skip them when there is nothing new to work on."""
        if not job.get("system"):
            return None
        if job["id"] == "memory-upkeep":
            n = len(self.room.agent.transcript)
            if n == job.get("_seen_len"):
                return "no new conversation since the last run"
            job["_seen_len"] = n
        if job["id"] == "morning-brief" and now - self.last_user_activity > 7 * 86400:
            return "user inactive for a week"
        return None

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------ execute --
    def _execute(self, job: dict, scheduled_for: int, reason: str, attempt: int = 1):
        from ..agent.loop import Agent
        CONFIG.set_home(self.home)
        jid = job["id"]
        run_id = self.store.start_run(jid, scheduled_for if reason == "schedule" else int(time.time()), reason, attempt) if self.store else f"run_{uuid.uuid4().hex[:8]}"
        if run_id is None:
            return  # already claimed
        self.running.add(jid)
        self.room.on_event("scheduled_run", {"job_id": jid, "run_id": run_id, "title": job.get("title", jid), "status": "running"})
        role = job.get("role", "scheduler_worker")
        worker = Agent(role, depth=1, llm=self.room.agent.llm, memory=self.room.memory, tz=self.room.agent.tz,
                       label=job.get("title", jid), on_event=self.room.on_event, parent=self.room.agent)
        worker.exclude_ns |= {"subagent", "browser", "cron", "hooks"}
        worker.store = self.store
        excerpt = ""
        if role == "memory_flush":
            recent = [m for m in self.room.agent.transcript[-40:] if m.get("role") in ("user", "assistant") and m.get("content")]
            excerpt = "\n\n## Recent conversation excerpt\n" + "\n".join(f"{m['role']}: {m['content'][:600]}" for m in recent)
        task = (f"[Scheduled Task] id={jid} title={job.get('title', jid)} run={run_id} attempt={attempt}\n"
                f"{assembler.time_lines(self.room.agent.tz)['time_tag']}\n\n{job.get('body', '')}{excerpt}\n\n"
                "## Execution contract\nDo the task now with your tools. Finish with a concise result summary as your final message: "
                "what you did, what you found, and anything the user should hear. Do not address the user directly.")
        status, summary, error, timed_out = "succeeded", None, None, False
        timeout = int(job.get("timeout_secs", 3600))
        done = threading.Event()
        result: dict = {}

        def run():
            try:
                result["text"] = worker.run_turn(task)
            except Exception as e:  # noqa: BLE001
                result["error"] = f"{type(e).__name__}: {e}"
            done.set()

        threading.Thread(target=run, daemon=True).start()
        if not done.wait(timeout):
            worker.closed = True
            status, error, timed_out = "failed", f"timed out after {timeout}s", True
        elif result.get("error"):
            status, error = "failed", result["error"]
        else:
            summary = result.get("text") or "(no summary)"
        if self.store:
            self.store.finish_run(run_id, status, summary, error, timed_out)
            self.store.job_after_run(jid, status, job.get("next_run_at_utc"), bool(job.get("enabled", True)))
        job["last_status"], job["last_run_at_utc"] = status, int(time.time())
        self.running.discard(jid)
        self.room.on_event("scheduled_run", {"job_id": jid, "run_id": run_id, "title": job.get("title", jid), "status": status})
        retry = job.get("retry") or {}
        if status == "failed" and retry.get("on_failure") and attempt <= int(retry.get("max_retries", 0)):
            self.pool.submit(self._execute, job, scheduled_for, "retry", attempt + 1)
            return
        if role == "memory_flush" and status == "succeeded":
            return  # bookkeeping; nothing for the user
        self.room.agent.deliver(f"[Scheduled job result] id={jid} title={job.get('title', jid)} status={status} run={run_id}\n"
                                f"{summary or error}\n\n(Decide whether this is worth the user's attention; a result they arranged to receive always surfaces.)")

    # -------------------------------------------------------------- hooks --
    def hook_add(self, spec: dict, update: bool = False) -> dict:
        hid = spec.get("id", "")
        if not JOB_ID.match(hid):
            raise ScheduleError("id must be short kebab-case")
        existing = self.hooks.get(hid)
        if update and not existing:
            raise ScheduleError(f"no hook {hid}")
        raw = str(spec.get("script_path") or (existing or {}).get("script_path") or "")
        # `~` is the agent's home, never the host user's
        if raw.startswith("~/"):
            script = self.home / raw[2:]
        elif raw.startswith("/"):
            script = pathlib.Path(raw)
        else:
            script = self.home / raw
        if not script.exists():
            raise ScheduleError(f"write the script first: {script} does not exist (paths resolve against your home, ~)")
        h = {**(existing or {}), "id": hid, "script_path": str(script), "prompt": spec.get("prompt", (existing or {}).get("prompt", "")),
             "poll_interval_secs": int(spec.get("poll_interval_secs", (existing or {}).get("poll_interval_secs", 60))),
             "script_timeout_secs": int(spec.get("script_timeout_secs", (existing or {}).get("script_timeout_secs", 600))),
             "delivery": spec.get("delivery") or (existing or {}).get("delivery") or [{"surface": "main"}],
             "enabled": (existing or {}).get("enabled", False), "created_at": (existing or {}).get("created_at", time.time())}
        self.hooks[hid] = h
        (self.home / "hooks/definitions" / f"{hid}.json").write_text(json.dumps(h, indent=1))
        return h

    def hook_set_enabled(self, hid: str, enabled: bool) -> dict:
        h = self.hooks.get(hid)
        if not h:
            raise ScheduleError(f"no hook {hid}")
        h["enabled"] = enabled
        self.hook_next[hid] = 0
        (self.home / "hooks/definitions" / f"{hid}.json").write_text(json.dumps(h, indent=1))
        return h

    def hook_remove(self, hid: str) -> dict:
        if hid not in self.hooks:
            raise ScheduleError(f"no hook {hid}")
        self.hooks.pop(hid)
        (self.home / "hooks/definitions" / f"{hid}.json").unlink(missing_ok=True)
        return {"id": hid, "removed": True}

    def hook_logs(self, hid: str, limit: int = 50) -> list[dict]:
        p = self.home / "hooks/logs" / f"{hid}.jsonl"
        if not p.exists():
            return []
        lines = p.read_text().splitlines()[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out

    def _poll_hook(self, h: dict, dry_run: bool) -> dict:
        from ..tools.local import _env
        result_file = self.home / "hooks/state" / f".{h['id']}.result"
        result_file.write_text("")
        CONFIG.set_home(self.home)  # this pool thread has no turn context; pin the agent's home explicitly
        env = _env()
        env.update({"HOME": str(self.home), "HATCH_HOOK_RUNTIME": str(REPO / "superapp/scheduler/hook_runtime.sh"),
                    "HATCH_HOOK_RESULT": str(result_file), "HATCH_HOOK_DRY_RUN": "1" if dry_run else "0", "HATCH_HOOK_ID": h["id"]})
        started = time.time()
        try:
            p = subprocess.run(["bash", h["script_path"]], cwd=str(self.home), env=env, capture_output=True, text=True,
                               timeout=int(h.get("script_timeout_secs", 600)))
            exit_code, stderr = p.returncode, p.stderr[-2000:]
        except subprocess.TimeoutExpired:
            exit_code, stderr = -1, "script timed out"
        lines = [json.loads(ln) for ln in result_file.read_text().splitlines() if ln.strip()]
        verdicts = [ln for ln in lines if ln.get("kind") in ("silent", "wake")]
        decision = verdicts[-1] if verdicts else {"kind": "invalid", "reason": "script ended without exactly one silent or wake"}
        if len(verdicts) > 1:
            decision = {"kind": "invalid", "reason": "script emitted more than one verdict"}
        entry = {"ts": started, "hook": h["id"], "dry_run": dry_run, "exit_code": exit_code, "decision": decision.get("kind"),
                 "reason": decision.get("reason"), "payload": decision.get("payload"), "observations": [ln for ln in lines if ln.get("kind") == "observation"],
                 "stderr": stderr, "duration_ms": int((time.time() - started) * 1000)}
        with (self.home / "hooks/logs" / f"{h['id']}.jsonl").open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        if not dry_run:
            if any(ln.get("kind") == "disable_after_run" for ln in lines):
                self.hook_set_enabled(h["id"], False)
            if decision.get("kind") == "wake":
                self.pool.submit(self._run_hook_worker, h, decision)
        return entry

    def _run_hook_worker(self, h: dict, decision: dict):
        from ..agent.loop import Agent
        worker = Agent("event_hook", depth=1, llm=self.room.agent.llm, memory=self.room.memory, tz=self.room.agent.tz,
                       label=f"hook {h['id']}", on_event=self.room.on_event, parent=self.room.agent)
        worker.exclude_ns |= {"subagent", "browser", "cron", "hooks"}
        worker.store = self.store
        task = (f"[Hook Event] hook={h['id']} phase=execute\n{assembler.time_lines(self.room.agent.tz)['time_tag']}\n"
                f"Wake reason: {decision.get('reason')}\nPayload: {json.dumps(decision.get('payload'), default=str)}\n\n"
                f"{h.get('prompt', '')}\n\n## Execution contract\nInvestigate with your tools and finish with a concise execute summary: "
                "what the event was, what you verified, and whether it needs the user's attention.")
        try:
            summary = worker.run_turn(task)
        except Exception as e:  # noqa: BLE001
            summary = f"(hook worker failed: {type(e).__name__}: {e})"
        self.room.agent.deliver(f"[Hook event result] hook={h['id']} reason={decision.get('reason')}\n{summary}\n\n"
                                "(Decide whether this is worth the user's attention.)")
