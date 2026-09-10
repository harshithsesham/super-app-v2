"""Assemble a role's system prompt from the Muse prompt blocks.

The blocks are verbatim reconstructions with `{placeholder}` slots. The
runtime fills the slots it owns (time, environment map, runtime facts,
delegation rules); every other brace expression is left untouched because
several blocks show literal formats like `L{start}-L{end}` to the model.
"""
from __future__ import annotations
import pathlib, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import yaml
from ..config import CONFIG, REPO

BLOCKS = CONFIG.blocks_dir
ROLES = yaml.safe_load((pathlib.Path(__file__).parent / "roles.yaml").read_text(encoding="utf-8"))

ENV_MAP_CHAT = ["computer", "browser", "chats", "skills", "subagents", "runtime",
                "scheduled_work", "hooks", "artifacts", "devices", "tracking", "user_goals"]
ENV_MAP_SUBAGENT = ["computer", "skills", "subagents", "runtime"]


def block(path: str) -> str:
    p = BLOCKS / path
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def env_map(names: list[str]) -> str:
    return "\n".join(b for n in names if (b := block(f"shared/environment/{n}.md")))


def time_lines(tz: str) -> dict:
    now = datetime.now(ZoneInfo(tz))
    nearby = []
    for d in range(-3, 8):
        day = now + timedelta(days=d)
        nearby.append(f"{day.strftime('%a %Y-%m-%d')}" + (" (today)" if d == 0 else ""))
    return {
        "current_date_line": f"The current date and time is {now.strftime('%A %Y-%m-%d %H:%M:%S %Z')} ({tz}).",
        "year_anchor_line": f"The current year is {now.year}. Do not assume an earlier year from training data.",
        "temporal_awareness_window": f"Now: {now.strftime('%A %Y-%m-%d %H:%M %Z')} ({tz}).",
        "nearby_dates_reference": "Nearby dates for reference: " + "; ".join(nearby) + ".",
        "time_tag": f"[{now.strftime('%a %Y-%m-%d %H:%M:%S %Z')}] [client_timezone={tz}]",
    }


def default_context(role: str, *, tz: str, assistant: str, runtime_section: str,
                    standing_files: str, skills_section: str, depth: int = 0) -> dict:
    ctx = {
        "assistant": assistant,
        "deferred_stub_marker": "deferred",
        "project_context": "",
        "hatch_environment": "prod",
        "chat_environment_map": env_map(ENV_MAP_CHAT),
        "memory_recall_section": "## Memory\n" + block("shared/memory_recall_doctrine.md") + "\n"
                                 + block("agent/person_records.md").split("\nThe memory files")[0],
        "self_evolution_section": "### How You Evolve\nBackground upkeep consolidates conversations into `~/MEMORY.md` "
                                  "hourly, maintains people and group pages, and distills the bank files under "
                                  "`~/memory/bank/`. " + block("chat/alignment_status_pointer.md"),
        "relationships_section": "",
        "goals_section": "",
        "prompt_injection_defense": "",
        "current_location_section": block("shared/current_location_coordinates_unavailable.md"),
        "runtime_facts": runtime_section,
        "subagents_section": block("shared/environment/subagents.md"),
        "credential_fill_delegation_rule": "\n" + block("chat/tool_rules_credential_fill.md"),
        "deep_research_delegation_rule": "",
        "cron_created_acknowledgement": block("chat/cron_created_acknowledgement.md") + " ",
        "date_batch_check_guidance": block("chat/date_batch_check_unavailable.md"),
        "security_policy": "",
        "alignment_status_pointer": block("chat/alignment_status_pointer.md"),
        # delegation doctrine slots (shared/memory_recall_doctrine.md)
        "responsive_clause": "responsive to the user",
        "overload_consequence": "overload your own context or stall the conversation",
        "after_spawn_clause": "end your turn with a brief note of what is in progress so the user can keep talking",
        "synthesis_sentence": "When the reports arrive, synthesize them for the user rather than forwarding them raw.",
        "fanout_bullet": "Fan out independent pieces to several subagents at once (up to "
                         f"{CONFIG.resources.get('max_concurrent_agents', 8)} run concurrently) and combine their reports.",
        "extra_delegation_bullet": "",
        "task_content_bullet": "Give each subagent a complete brief: the goal, the context it needs, constraints, "
                               "and exactly what to report back. It starts with no transcript.",
        "transcript_fact": "A subagent starts with no inherited transcript; only the brief you send reaches it.",
        # skills routing slots (shared/environment/devices.md)
        "skills_blocked_escalation": "If you are truly blocked, return to the user and explain where you are blocked.",
        "skills_no_skill_browser_route": "When no skill covers a service, the live browser (`browser.spawn_task`) "
                                         "is the route for actions on that service's website.",
        # subagent role
        "subagent_identity_intro": "a background worker spawned by the main agent to complete one delegated task",
        "history_inheritance_section": "- You start with no inherited transcript. Your parent's brief is your whole context; "
                                       "if it lacks something you need, say so in your report rather than guessing.",
        "requester_description": "the user's main agent.",
        "max_spawn_depth": "2", "child_depth": str(depth),
        "can_spawn": "yes" if depth < 2 else "no",
        # computed sections
        "$standing_files": standing_files,
        "$runtime": runtime_section,
        "$skills": skills_section,
        "$environment_map": env_map(ENV_MAP_SUBAGENT if role != "chat" else ENV_MAP_CHAT),
    }
    ctx.update(time_lines(tz))
    return ctx


_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def fill(text: str, ctx: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), text)


def assemble(role: str, ctx: dict) -> str:
    parts = []
    for entry in ROLES[role]:
        if entry.startswith("$"):
            text = ctx.get(entry, "")
        else:
            text = block(entry)
        text = fill(fill(text, ctx), ctx).strip()  # twice: computed sections carry their own slots
        if text:
            parts.append(text)
    out = "\n\n".join(parts)
    # blocks rendered a bare placeholder name on its own line when the slot was empty; drop those
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", out).strip() + "\n"
