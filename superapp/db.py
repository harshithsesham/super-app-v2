"""Durable runtime state in Postgres, on the Muse schema (db/schema.sql).

Layout follows Muse: one database per user (Muse had one per cell). The
daemon creates `muse_<user>` on first use and applies the schema. Tables
written here and what they mean:

  agent.sessions / agent.agents            agent lifecycle (root, subagent, browser_task, scheduler_worker)
  runtime.events                           the transcript spine, one row per message / tool call / tool output
  runtime.messages, runtime.tool_calls,    normalized views of the same rows
  runtime.tool_outputs
  agent.compactions                        summaries that replaced older history
  agent.subagent_spawns                    child agent runs and their reports
  runtime.browser_tasks                    browser worker lifecycle
  agent.runtime_restart_checkpoints        an in-flight turn, cleared when it ends; used for restart recovery
  scheduler.jobs / job_definitions /       cron jobs, their task text, and every run
  job_runs / events

Connection: DATABASE_URL, or built from SUPERAPP_DB_PASSWORD + SUPERAPP_DB_HOST
(default `db`, the compose service on the box). Without either, the store is
off and the daemon falls back to the JSON transcript file.
"""
from __future__ import annotations
import json, os, pathlib, re, threading, time, uuid
from contextlib import contextmanager
import psycopg
from psycopg_pool import ConnectionPool
from .config import REPO

_admin_pool: ConnectionPool | None = None
_lock = threading.Lock()
_stores: dict[str, "Store"] = {}


def admin_url() -> str | None:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    pw = os.environ.get("SUPERAPP_DB_PASSWORD")
    if not pw:
        return None
    host = os.environ.get("SUPERAPP_DB_HOST", "db")
    return f"postgresql://superapp:{pw}@{host}:5432/{os.environ.get('SUPERAPP_DB_ADMIN_DB', 'superapp')}"


def enabled() -> bool:
    return admin_url() is not None


def _dbname(user: str) -> str:
    return "muse_" + re.sub(r"[^a-z0-9_]", "_", user.lower())[:40]


def _url_for(dbname: str) -> str:
    base = admin_url()
    assert base
    return re.sub(r"/[^/]*$", f"/{dbname}", base)


def _ensure_database(dbname: str):
    with psycopg.connect(admin_url(), autocommit=True) as c:
        exists = c.execute("select 1 from pg_database where datname=%s", (dbname,)).fetchone()
        if not exists:
            c.execute(f'CREATE DATABASE "{dbname}"')
    with psycopg.connect(_url_for(dbname), autocommit=True) as c:
        have = c.execute("select 1 from information_schema.tables where table_schema='runtime' and table_name='events'").fetchone()
        if not have:
            c.execute((REPO / "db/schema.sql").read_text(encoding="utf-8"))


def store_for(user: str) -> "Store | None":
    if not enabled():
        return None
    with _lock:
        if user not in _stores:
            db = _dbname(user)
            _ensure_database(db)
            _stores[user] = Store(user, ConnectionPool(_url_for(db), min_size=1, max_size=6, kwargs={"autocommit": True}))
        return _stores[user]


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, user: str, pool: ConnectionPool):
        self.user = user
        self.pool = pool
        self.session_id = f"session_{user}"
        self.exec("insert into agent.sessions (session_id) values (%s) on conflict do nothing", (self.session_id,))

    # ------------------------------------------------------------ helpers --
    @contextmanager
    def conn(self):
        with self.pool.connection() as c:
            yield c

    def exec(self, sql: str, params: tuple = ()):
        with self.conn() as c:
            c.execute(sql, params)

    def one(self, sql: str, params: tuple = ()):
        with self.conn() as c:
            return c.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()):
        with self.conn() as c:
            return c.execute(sql, params).fetchall()

    # ------------------------------------------------------------- agents --
    def upsert_agent(self, agent_id: str, kind: str, status: str, depth: int = 0, parent_agent_id: str | None = None,
                     model: str = "", agent_type: str | None = None):
        self.exec("""insert into agent.agents (agent_id, id, session_id, kind, parent_agent_id, root_session_id, model, status, depth, agent_type)
                     values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     on conflict (agent_id) do update set status=excluded.status, updated_at=extract(epoch from now())::bigint""",
                  (agent_id, agent_id, self.session_id, kind, parent_agent_id, self.session_id, model, status, depth, agent_type))

    def set_agent_status(self, agent_id: str, status: str, last_assistant_message: str | None = None):
        self.exec("update agent.agents set status=%s, updated_at=extract(epoch from now())::bigint, "
                  "last_assistant_message=coalesce(%s, last_assistant_message) where agent_id=%s",
                  (status, last_assistant_message, agent_id))

    # --------------------------------------------------------- transcript --
    def _event(self, agent_id: str, kind: str, name: str, role: str | None, payload: dict, surface: str = "main",
               visibility: str = "internal", message_id: str | None = None) -> int:
        row = self.one("""insert into runtime.events (event_kind, event_name, transcript_surface, visibility, source, role,
                          message_id, agent_id, payload_json) values (%s,%s,%s,%s,'daemon',%s,%s,%s,%s) returning event_seq""",
                       (kind, name, surface, visibility, role, message_id, agent_id, json.dumps(payload, default=str)))
        return int(row[0])

    def record_transcript_entry(self, agent_id: str, entry: dict) -> int:
        """Persist one OpenAI-format transcript entry (user/assistant/tool) so it can be replayed exactly."""
        role = entry.get("role")
        if role == "tool":
            seq = self._event(agent_id, "tool_output", "tool_output", "tool", entry)
            content = entry.get("content") or ""
            status = "error" if '"status": "error"' in content[:40] else "ok"
            self.exec("insert into runtime.tool_outputs (event_seq, call_id, status, output_text) values (%s,%s,%s,%s)",
                      (seq, entry.get("tool_call_id"), status, content[:200000]))
            return seq
        if role == "assistant" and entry.get("tool_calls"):
            seq = None
            for tc in entry["tool_calls"]:
                seq = self._event(agent_id, "tool_call", tc["function"]["name"], "assistant", entry)
                self.exec("insert into runtime.tool_calls (event_seq, call_id, tool_name, status, arguments_json) values (%s,%s,%s,'called',%s) "
                          "on conflict (call_id) do nothing",
                          (seq, tc["id"], tc["function"]["name"].replace("__", ".", 1), tc["function"]["arguments"]))
            if entry.get("content"):
                mid = f"msg_{uuid.uuid4().hex[:12]}"
                s2 = self._event(agent_id, "message", "assistant_commentary", "assistant", {"role": "assistant", "content": entry["content"]},
                                 visibility="user_visible", message_id=mid)
                self.exec("insert into runtime.messages (message_id, event_seq, role, body) values (%s,%s,'assistant',%s)", (mid, s2, entry["content"]))
            return seq or 0
        mid = f"msg_{uuid.uuid4().hex[:12]}"
        visibility = "user_visible" if role in ("user", "assistant") else "internal"
        seq = self._event(agent_id, "message", role or "message", role, entry, visibility=visibility, message_id=mid)
        self.exec("insert into runtime.messages (message_id, event_seq, role, body) values (%s,%s,%s,%s)",
                  (mid, seq, role, (entry.get("content") or "")[:200000]))
        return seq

    def load_transcript(self, agent_id: str) -> list[dict]:
        """Replay: the latest compaction summary first (it stands in for everything before it), then the live tail."""
        rows = self.all("""select payload_json, event_name from runtime.events where agent_id=%s and event_kind in ('message','tool_call','tool_output')
                           and visibility <> 'compacted' and event_name <> 'assistant_commentary' order by event_seq""", (agent_id,))
        summary, tail = [], []
        for p, name in rows:
            try:
                m = json.loads(p)
                for tc in m.get("tool_calls") or []:   # rows written before arguments were normalised
                    fn = tc.get("function") or {}
                    try:
                        ok = isinstance(json.loads(fn.get("arguments") or ""), dict)
                    except json.JSONDecodeError:
                        ok = False
                    if not ok:
                        fn["arguments"] = "{}"
                (summary if name == "compaction_summary" else tail).append(m)
            except (TypeError, json.JSONDecodeError):
                continue
        return summary[-1:] + tail

    def record_compaction(self, agent_id: str, summary: str, keep_from_index: int):
        """Mark the compacted prefix and store the summary as a message, mirroring agent.compactions."""
        rows = self.all("""select event_seq from runtime.events where agent_id=%s and event_kind in ('message','tool_call','tool_output')
                           and visibility <> 'compacted' and event_name <> 'assistant_commentary' order by event_seq""", (agent_id,))
        seqs = [r[0] for r in rows]
        cut = seqs[:keep_from_index]
        if cut:
            self.exec("update runtime.events set visibility='compacted' where agent_id=%s and event_seq <= %s", (agent_id, cut[-1]))
        # an earlier summary is now part of what the new one replaces
        self.exec("update runtime.events set visibility='compacted' where agent_id=%s and event_name='compaction_summary'", (agent_id,))
        self.exec("insert into agent.compactions (agent_id, replacement_history_first_seq, replacement_history_last_seq, summary_text) values (%s,%s,%s,%s)",
                  (agent_id, cut[0] if cut else None, cut[-1] if cut else None, summary))
        body = "[Earlier conversation summary from compaction]\n" + summary
        mid = f"msg_{uuid.uuid4().hex[:12]}"
        seq = self._event(agent_id, "message", "compaction_summary", "user", {"role": "user", "content": body}, message_id=mid)
        self.exec("insert into runtime.messages (message_id, event_seq, role, body) values (%s,%s,'user',%s)", (mid, seq, body[:200000]))

    # ---------------------------------------------------------- checkpoints --
    def checkpoint(self, agent_id: str, mode: str, payload: dict, recovery_class: str = "foreground_root"):
        self.exec("""insert into agent.runtime_restart_checkpoints (agent_id, mode, payload_json, created_at, updated_at, recovery_class)
                     values (%s,%s,%s,%s,%s,%s) on conflict (agent_id) do update set mode=excluded.mode, payload_json=excluded.payload_json,
                     updated_at=excluded.updated_at""", (agent_id, mode, json.dumps(payload, default=str), now_ms(), now_ms(), recovery_class))

    def clear_checkpoint(self, agent_id: str):
        self.exec("delete from agent.runtime_restart_checkpoints where agent_id=%s", (agent_id,))

    def pending_checkpoints(self) -> list[dict]:
        return [{"agent_id": a, "mode": m, "payload": json.loads(p or "{}"), "recovery_class": r}
                for a, m, p, r in self.all("select agent_id, mode, payload_json, recovery_class from agent.runtime_restart_checkpoints")]

    # ---------------------------------------------------------- subagents --
    def record_spawn(self, parent_agent_id: str, child_agent_id: str, prompt: str, depth: int, spawn_call_id: str | None = None):
        self.exec("""insert into agent.subagent_spawns (parent_agent_id, child_agent_id, status, prompt, child_depth, agent_type, spawn_call_id)
                     values (%s,%s,'running',%s,%s,'subagent',%s) on conflict (child_agent_id) do nothing""",
                  (parent_agent_id, child_agent_id, prompt[:20000], depth, spawn_call_id))

    def finish_spawn(self, child_agent_id: str, status: str, final_response: str | None):
        self.exec("update agent.subagent_spawns set status=%s, final_response=%s, completed_at=extract(epoch from now())::bigint where child_agent_id=%s",
                  (status, (final_response or "")[:50000], child_agent_id))

    def interrupt_open_spawns(self) -> int:
        with self.conn() as c:
            return c.execute("update agent.subagent_spawns set status='interrupted' where status='running'").rowcount

    # ------------------------------------------------------ browser tasks --
    def upsert_browser_task(self, t: dict):
        self.exec("""insert into runtime.browser_tasks (task_id, root_session_id, owner_agent_id, root_message_id, stream_owner_message_id, status, title,
                     step_count, initial_instruction, parent_agent_id, outcome_status, outcome_reason, terminal_reason, completed_at, outcome_at)
                     values (%s,%s,%s,'','',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     on conflict (task_id) do update set status=excluded.status, step_count=excluded.step_count, outcome_status=excluded.outcome_status,
                     outcome_reason=excluded.outcome_reason, terminal_reason=excluded.terminal_reason, completed_at=excluded.completed_at,
                     outcome_at=excluded.outcome_at, updated_at=now()""",
                  (t["task_id"], self.session_id, t["owner_agent_id"], t["status"], t["title"], t.get("step_count", 0),
                   t.get("initial_instruction"), t.get("parent_agent_id"), t.get("outcome_status"), (t.get("outcome_reason") or "")[:20000] or None,
                   t.get("terminal_reason"), t.get("completed_at"), t.get("outcome_at")))

    def interrupt_open_browser_tasks(self) -> int:
        with self.conn() as c:
            return c.execute("update runtime.browser_tasks set status='failed', terminal_reason='daemon_restart', outcome_status='failed', "
                             "completed_at=now() where status in ('queued','running','needs_user')").rowcount

    # ---------------------------------------------------------- scheduler --
    def upsert_job(self, job: dict):
        self.exec("""insert into scheduler.jobs (job_id, is_heartbeat, source_path, schedule_kind, enabled, schedule_expr, timezone, retry_on_failure,
                     max_retries, delivery_targets_json, next_run_at, next_run_at_utc, updated_at_utc)
                     values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s)
                     on conflict (job_id) do update set source_path=excluded.source_path, schedule_kind=excluded.schedule_kind, enabled=excluded.enabled,
                     schedule_expr=excluded.schedule_expr, timezone=excluded.timezone, retry_on_failure=excluded.retry_on_failure,
                     max_retries=excluded.max_retries, delivery_targets_json=excluded.delivery_targets_json, next_run_at=excluded.next_run_at,
                     next_run_at_utc=excluded.next_run_at_utc, updated_at_utc=excluded.updated_at_utc, updated_at=now()""",
                  (job["id"], job.get("system", False), job.get("source_path"), job["schedule"]["kind"], job.get("enabled", True), job["cron_expr"],
                   job["schedule"].get("timezone", "UTC"), bool(job.get("retry", {}).get("on_failure", False)), int(job.get("retry", {}).get("max_retries", 0)),
                   json.dumps(job.get("delivery") or []), job.get("next_run_at_utc") or 0, int(job.get("next_run_at_utc") or 0), now_ms() // 1000))
        ver = self.one("select coalesce(max(version),0)+1 from scheduler.job_definitions where job_id=%s", (job["id"],))[0]
        self.exec("update scheduler.job_definitions set retired_at=now() where job_id=%s and retired_at is null", (job["id"],))
        self.exec("insert into scheduler.job_definitions (job_id, version, task_text) values (%s,%s,%s)",
                  (job["id"], ver, json.dumps({k: v for k, v in job.items() if k != "next_run_at_utc"}, default=str)))

    def delete_job(self, job_id: str):
        self.exec("delete from scheduler.jobs where job_id=%s", (job_id,))
        self.exec("update scheduler.job_definitions set retired_at=now() where job_id=%s and retired_at is null", (job_id,))

    def load_jobs(self) -> list[dict]:
        rows = self.all("""select d.task_text, j.enabled, j.next_run_at_utc, j.last_run_at_utc, j.last_status, j.consecutive_failures
                           from scheduler.jobs j join scheduler.job_definitions d on d.job_id=j.job_id and d.retired_at is null""")
        out = []
        for task_text, enabled, next_utc, last_utc, last_status, fails in rows:
            try:
                job = json.loads(task_text)
            except json.JSONDecodeError:
                continue
            job.update({"enabled": enabled, "next_run_at_utc": next_utc, "last_run_at_utc": last_utc, "last_status": last_status,
                        "consecutive_failures": fails})
            out.append(job)
        return out

    def job_after_run(self, job_id: str, status: str, next_run_at_utc: int | None, enabled: bool):
        self.exec("""update scheduler.jobs set last_run_at_utc=%s, last_success_at_utc=case when %s='succeeded' then %s else last_success_at_utc end,
                     last_status=%s, consecutive_failures=case when %s='succeeded' then 0 else consecutive_failures+1 end,
                     next_run_at=to_timestamp(%s), next_run_at_utc=%s, enabled=%s, updated_at=now() where job_id=%s""",
                  (now_ms() // 1000, status, now_ms() // 1000, status, status, next_run_at_utc or 0, next_run_at_utc or 0, enabled, job_id))

    def start_run(self, job_id: str, scheduled_for_utc: int, trigger_reason: str, attempt: int = 1) -> str | None:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        try:
            self.exec("""insert into scheduler.job_runs (run_id, job_id, scheduled_for, scheduled_for_utc, trigger_reason, started_at, started_at_utc, status, attempt, worker_claimed_at_utc)
                         values (%s,%s,to_timestamp(%s),%s,%s,now(),%s,'running',%s,%s)""",
                      (run_id, job_id, scheduled_for_utc, scheduled_for_utc, trigger_reason, now_ms() // 1000, attempt, now_ms() // 1000))
        except psycopg.errors.UniqueViolation:
            return None  # this scheduled occurrence was already claimed (restart race)
        self.exec("insert into scheduler.events (job_id, run_id, event_name) values (%s,%s,'run_started')", (job_id, run_id))
        return run_id

    def finish_run(self, run_id: str, status: str, result_summary: str | None, error_text: str | None, timed_out: bool = False):
        self.exec("""update scheduler.job_runs set status=%s, result_summary=%s, error_text=%s, finished_at=now(), finished_at_utc=%s,
                     worker_execution_timed_out=%s where run_id=%s""",
                  (status, (result_summary or "")[:20000] or None, (error_text or "")[:20000] or None, now_ms() // 1000, timed_out, run_id))
        self.exec("insert into scheduler.events (job_id, run_id, event_name, detail) select job_id, run_id, %s, %s from scheduler.job_runs where run_id=%s",
                  (f"run_{status}", (error_text or result_summary or "")[:500], run_id))

    def interrupt_open_runs(self) -> int:
        with self.conn() as c:
            return c.execute("update scheduler.job_runs set status='failed', error_text='daemon restarted during the run', finished_at=now() "
                             "where status in ('queued','running')").rowcount

    def runs(self, job_id: str | None = None, limit: int = 20) -> list[dict]:
        rows = self.all("""select run_id, job_id, status, attempt, trigger_reason, scheduled_for_utc, started_at_utc, finished_at_utc, result_summary, error_text
                           from scheduler.job_runs where (%s::text is null or job_id=%s::text) order by scheduled_for_utc desc limit %s""", (job_id, job_id, limit))
        keys = ["run_id", "job_id", "status", "attempt", "trigger_reason", "scheduled_for_utc", "started_at_utc", "finished_at_utc", "result_summary", "error_text"]
        return [dict(zip(keys, r)) for r in rows]

    def run_counts(self, job_id: str | None = None) -> dict:
        r = self.one("""select count(*) filter (where status='queued'), count(*) filter (where status='running') from scheduler.job_runs
                        where (%s::text is null or job_id=%s::text)""", (job_id, job_id))
        return {"queued": r[0], "running": r[1]}
