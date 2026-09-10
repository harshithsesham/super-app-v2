"""The Hub: the at-a-glance page from the earlier app, now assembled from
this runtime: the latest brief the agent wrote, live inbox numbers through
the Gmail connector, goals, and the services the agent can reach.
"""
from __future__ import annotations
import json, pathlib, time
from datetime import datetime
from zoneinfo import ZoneInfo
from .connectors import vault
from .connectors.gmail import GmailClient, GmailError
from .prompts import skills_catalog

GRID = [
    {"name": "Inbox", "skill": "gmail", "tone": "indigo", "ask": "Summarise my inbox and tell me what needs me."},
    {"name": "Calendar", "skill": "google-calendar", "tone": "mint", "ask": "What's on my calendar today and tomorrow?"},
    {"name": "Finances", "skill": "plaid", "tone": "amber", "ask": "Where is my money going this month?"},
    {"name": "Health", "skill": "apple-healthkit", "tone": "rose", "ask": "How am I doing on movement and sleep this week?"},
    {"name": "Shopping", "skill": "shopping", "tone": "indigo", "ask": "Help me find and compare something to buy."},
    {"name": "Flights", "skill": "flightaware", "tone": "mint", "ask": "Watch a flight for me."},
]


def _greeting(tz: str, name: str) -> tuple[str, str]:
    now = datetime.now(ZoneInfo(tz))
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    who = f", {name.split()[0]}" if name else ""
    return f"Good {part}{who}.", now.strftime("%a %d %b · %H:%M").upper()


def _inbox(home: pathlib.Path) -> dict:
    tok = vault.load("gmail", home)
    if not tok:
        return {"connected": False, "headline": "Connect your inbox", "body": "Link Gmail and I'll keep it at zero with you.",
                "stats": []}
    c = GmailClient(tok, on_refresh=lambda t: vault.store("gmail", t, home))
    try:
        unread = c.api("GET", "/labels/UNREAD")
        today = c.list_messages("in:inbox newer_than:1d", 1)
        n_unread = int(unread.get("threadsUnread", 0))
        n_today = int(today.get("resultSizeEstimate", 0))
        headline = "Inbox is clear." if n_unread == 0 else f"{n_unread} unread thread{'s' if n_unread != 1 else ''} waiting."
        body = f"{n_today} arrived today. Ask me what needs you and I'll draft the replies."
        return {"connected": True, "email": tok.get("email"), "headline": headline, "body": body,
                "stats": [{"n": n_unread, "label": "unread"}, {"n": n_today, "label": "today"}]}
    except GmailError as e:
        return {"connected": True, "email": tok.get("email"), "headline": "Inbox check hit a snag.", "body": str(e)[:120], "stats": []}


def _brief(home: pathlib.Path) -> dict:
    p = home / "workspace" / "feed.json"
    posts = []
    try:
        posts = json.loads(p.read_text()) if p.exists() else []
    except json.JSONDecodeError:
        posts = []
    latest = sorted(posts, key=lambda x: x.get("ts", 0))[-1] if posts else None
    if not latest:
        return {"ready": False, "title": "Morning briefing", "sub": "Your first brief lands after a day together.", "text": ""}
    return {"ready": True, "title": latest.get("title", "Morning briefing"), "sub": latest.get("body", "")[:140],
            "text": f"{latest.get('title','')}. {latest.get('body','')}", "kicker": latest.get("kicker", "")}


def _goals(home: pathlib.Path) -> dict:
    p = home / "workspace" / "goals.json"
    try:
        goals = json.loads(p.read_text()) if p.exists() else []
    except json.JSONDecodeError:
        goals = []
    return {"open": sum(1 for g in goals if not g.get("done")), "done": sum(1 for g in goals if g.get("done"))}


def build(home: pathlib.Path, tz: str, name: str) -> dict:
    greeting, stamp = _greeting(tz, name)
    statuses = {s["name"]: s["status"] for s in skills_catalog.catalog(home)}
    grid = [dict(g, status=statuses.get(g["skill"], "available"),
                 sub="LIVE" if statuses.get(g["skill"]) == "connected" else "TAP TO CONNECT") for g in GRID]
    return {"greeting": greeting, "stamp": stamp, "brief": _brief(home), "inbox": _inbox(home), "goals": _goals(home),
            "grid": grid, "generated_at": time.time()}
