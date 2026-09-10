"""Approval cards: the gate in front of anything that sends or spends.

A connector command that needs consent asks the daemon for an approval and
blocks until the user answers on a card rendered outside the chat. The
agent never sees the card; it only sees the command's result. A denial is
final for that attempt.
"""
from __future__ import annotations
import threading, time, uuid
from dataclasses import dataclass, field


@dataclass
class Approval:
    id: str
    kind: str                 # e.g. gmail_send
    title: str                # "Send email · Muse wants to email jane@…"
    subtitle: str
    details: list[dict]       # [{label, value}]
    created_at: float = field(default_factory=time.time)
    decision: str | None = None    # allow | deny
    event: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "subtitle": self.subtitle,
                "details": self.details, "created_at": self.created_at, "decision": self.decision}


class ApprovalStore:
    def __init__(self, on_new=None, on_resolved=None):
        self.items: dict[str, Approval] = {}
        self.on_new = on_new
        self.on_resolved = on_resolved
        self._lock = threading.Lock()

    def request(self, kind: str, title: str, subtitle: str, details: list[dict], timeout_s: int = 600) -> str:
        a = Approval(id=f"apr_{uuid.uuid4().hex[:10]}", kind=kind, title=title, subtitle=subtitle, details=details)
        with self._lock:
            self.items[a.id] = a
        if self.on_new:
            self.on_new(a)
        a.event.wait(timeout_s)
        if a.decision is None:
            a.decision = "expired"
            if self.on_resolved:
                self.on_resolved(a)
        return a.decision

    def resolve(self, approval_id: str, decision: str) -> Approval | None:
        a = self.items.get(approval_id)
        if not a or a.decision is not None:
            return None
        a.decision = "allow" if decision == "allow" else "deny"
        a.event.set()
        if self.on_resolved:
            self.on_resolved(a)
        return a

    def pending(self) -> list[dict]:
        return [a.public() for a in self.items.values() if a.decision is None]
