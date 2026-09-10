"""The agent turn loop.

One Agent owns one transcript. A turn: drain runtime handoffs into the
transcript, add the time-tagged user message, then call the model until it
stops requesting tools. Tool results, subagent reports, and finished
background commands are delivered into the transcript by the runtime; the
model never polls for them.

Compaction summarizes the older transcript when it grows past the
configured budget, keeping the summary at the front, as Muse does.
"""
from __future__ import annotations
import json, queue, threading, uuid
from typing import Callable
from ..config import CONFIG
from ..llm import LLM
from ..memory.files import HomeMemory
from ..prompts import assembler, skills_catalog
from ..tools.registry import REGISTRY, ToolError, unwire

MAX_TOOL_ROUNDS = 60
TOOL_RESULT_CHARS = 12000

COMPACTION_PROMPT = (
    "You are compacting a long-running conversation between a personal agent and its user. "
    "Write a dense summary that preserves: durable facts about the user, decisions made, commitments and "
    "open tasks with their current status, identifiers copied exactly (names, dates, amounts, URLs, paths), "
    "and anything the agent promised to deliver. Drop chit-chat. Do not invent anything. Plain prose and lists."
)


def _approx_tokens(messages: list[dict]) -> int:
    return sum(len(json.dumps(m, default=str)) for m in messages) // 4


class Agent:
    def __init__(self, role: str = "chat", depth: int = 0, *, llm: LLM | None = None,
                 memory: HomeMemory | None = None, tz: str = "America/Chicago", label: str | None = None,
                 on_text: Callable[[str], None] | None = None, on_event: Callable[[str, dict], None] | None = None,
                 parent: "Agent | None" = None):
        self.id = f"agent_{uuid.uuid4().hex[:8]}"
        self.role, self.depth, self.tz, self.label, self.parent = role, depth, tz, label, parent
        self.llm = llm or LLM()
        self.memory = memory or HomeMemory()
        self.on_text = on_text or (lambda s: None)
        self.on_event = on_event or (lambda kind, data: None)
        self.transcript: list[dict] = []
        self.inbox: "queue.Queue[str]" = queue.Queue()
        self.closed = False
        self.status = "idle"
        self._lock = threading.Lock()
        # doctrine: subagents never get the browser, wallet, or purchase surfaces; depth>=2 cannot spawn
        self.exclude_ns: set[str] = set()
        if role != "chat":
            self.exclude_ns |= {"browser", "wallet", "credentials", "chat", "feed", "channel"}
        if depth >= 2:
            self.exclude_ns.add("subagent")

    # ------------------------------------------------------------ delivery --
    def deliver(self, text: str):
        """Runtime -> agent handoff (subagent report, finished background command, scheduled result)."""
        self.inbox.put(text)
        self.on_event("handoff", {"agent": self.id, "text": text[:200]})

    def _drain_inbox(self):
        while True:
            try:
                text = self.inbox.get_nowait()
            except queue.Empty:
                return
            self.transcript.append({"role": "user", "content": f"{self._time_tag()} [runtime handoff]\n{text}"})

    # -------------------------------------------------------------- prompt --
    def _time_tag(self) -> str:
        return assembler.time_lines(self.tz)["time_tag"]

    def assistant_name(self) -> str:
        for line in self.memory.read("IDENTITY.md").splitlines():
            if line.lower().startswith("name:") and line.split(":", 1)[1].strip():
                return line.split(":", 1)[1].strip()
        return "your assistant"

    def system_prompt(self) -> str:
        ctx = assembler.default_context(
            self.role, tz=self.tz, assistant=self.assistant_name(),
            runtime_section=REGISTRY.runtime_section(self.exclude_ns),
            standing_files="## Runtime Files (injected)\n" + self.memory.standing_files_section(),
            skills_section=skills_catalog.section(self.memory.home), depth=self.depth)
        return assembler.assemble("chat" if self.role == "chat" else "subagent", ctx)

    # ---------------------------------------------------------- compaction --
    def _maybe_compact(self):
        budget = int(CONFIG.conversation.get("max_context_tokens", 80000))
        if _approx_tokens(self.transcript) < budget * 0.8:
            return
        keep_from = None
        # keep the last ~12 messages, but cut only at a user-message boundary so tool pairs stay intact
        for i in range(max(0, len(self.transcript) - 12), -1, -1):
            if self.transcript[i]["role"] == "user":
                keep_from = i
                break
        if not keep_from:
            return
        older = self.transcript[:keep_from]
        text = "\n".join(f"{m['role']}: {m.get('content') or json.dumps(m.get('tool_calls', ''), default=str)}"
                         for m in older)
        summary = self.llm.quick(COMPACTION_PROMPT, text[-200000:], effort="low", max_tokens=4000)
        self.transcript = ([{"role": "user", "content": "[Earlier conversation summary from compaction]\n" + summary}]
                           + self.transcript[keep_from:])
        self.on_event("compaction", {"agent": self.id, "kept": len(self.transcript)})

    # ---------------------------------------------------------------- turn --
    def run_turn(self, user_text: str | None = None) -> str:
        with self._lock:
            self.status = "running"
            try:
                return self._run_turn(user_text)
            finally:
                self.status = "idle" if not self.closed else "closed"

    def _run_turn(self, user_text: str | None) -> str:
        CONFIG.set_home(self.memory.home)  # tools resolve ~ against this agent's home on this thread
        self._drain_inbox()
        if user_text is not None:
            self.transcript.append({"role": "user", "content": f"{self._time_tag()}\n{user_text}"})
        tools = REGISTRY.openai_tools(self.exclude_ns)
        effort = CONFIG.effort("root_agent" if self.depth == 0 else "subagent")
        final_text = ""
        for _ in range(MAX_TOOL_ROUNDS):
            if self.closed:
                return "[closed]"
            self._maybe_compact()
            messages = [{"role": "system", "content": self.system_prompt()}] + self.transcript
            content, tool_calls = self._stream_completion(messages, tools, effort)
            msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            self.transcript.append(msg)
            if not tool_calls:
                final_text = content or ""
                break
            for tc in tool_calls:
                self.transcript.append({"role": "tool", "tool_call_id": tc["id"], "content": self._run_tool(tc)})
            self._drain_inbox()
        else:
            final_text = "I hit my tool budget for this turn. Here is where things stand: " + (content or "")
        return final_text

    def _stream_completion(self, messages, tools, effort):
        content_parts: list[str] = []
        calls: dict[int, dict] = {}
        stream = self.llm.stream(messages, tools, effort=effort)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                self.on_text(delta.content)
            for tc in delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": tc.id or "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["function"]["arguments"] += tc.function.arguments
        tool_calls = [calls[i] for i in sorted(calls)]
        for tc in tool_calls:
            tc["id"] = tc["id"] or f"call_{uuid.uuid4().hex[:8]}"
        return "".join(content_parts), tool_calls

    def _run_tool(self, tc: dict) -> str:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError as e:
            return json.dumps({"status": "error", "code": "bad_arguments", "message": str(e)})
        self.on_event("tool_call", {"agent": self.id, "tool": unwire(name), "args": args})
        ctx = {"agent": self, "on_background_finish": self._on_background_finish}
        try:
            result = REGISTRY.dispatch(name, args, ctx)
            payload = {"status": "ok", "result": result}
        except ToolError as e:
            payload = {"status": "error", "code": "unavailable", "message": str(e)}
        except Exception as e:  # noqa: BLE001
            payload = {"status": "error", "code": "exception", "message": f"{type(e).__name__}: {e}"}
        text = json.dumps(payload, default=str)
        if len(text) > TOOL_RESULT_CHARS:
            text = text[:TOOL_RESULT_CHARS] + f'... [truncated {len(text) - TOOL_RESULT_CHARS} chars]'
        self.on_event("tool_result", {"agent": self.id, "tool": unwire(name), "status": payload["status"]})
        return text

    def _on_background_finish(self, session):
        tail = "".join(session.output[-60:])
        self.deliver(f"[Background command finished] session {session.id} exit_code={session.exit_code}\n"
                     f"command: {session.command[:200]}\n--- last output ---\n{tail[-6000:]}")
