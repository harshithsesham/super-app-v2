"""The agent's home-directory memory layout, mirroring Muse:

  ~/AGENTS.md ~/SOUL.md ~/IDENTITY.md ~/USER.md ~/TOOLS.md   standing files, injected every turn
  ~/MEMORY.md                                                curated long-term memory
  ~/memory/YYYY-MM-DD.md                                     daily logs
  ~/memory/bank/{experience,opinions,reflections,world}.md   runtime-managed distillations
  ~/memory/people/INDEX.md, ~/memory/groups/INDEX.md         relationship map
  ~/workspace/                                               everything the agent builds
"""
from __future__ import annotations
import pathlib, re
from datetime import date
from ..config import CONFIG

TEMPLATES = {
    "AGENTS.md": "# AGENTS.md\nHow to operate in this workspace: conventions and lessons learned.\n",
    "SOUL.md": "# SOUL.md\nPersona and tone. Fill in as you become someone.\n",
    "IDENTITY.md": "# IDENTITY.md\nname:\ncharacter:\nvibe:\nsignature_emoji:\n",
    "USER.md": "# USER.md\nname:\ncall_them:\ntimezone:\ncares_about:\n",
    "TOOLS.md": "# TOOLS.md\nNotes about tools and connected services that are specific to this user.\n",
    "MEMORY.md": "# MEMORY.md\n\n## Facts\n\n## Preferences\n\n## Commitments\n\n## Ongoing\n",
    "memory/people/INDEX.md": "# People\n(ordered by closeness; one page per person in this directory)\n",
    "memory/groups/INDEX.md": "# Groups\n",
    "memory/bank/experience.md": "", "memory/bank/opinions.md": "",
    "memory/bank/reflections.md": "", "memory/bank/world.md": "",
}
STANDING_FILES = ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "TOOLS.md", "MEMORY.md",
                  "memory/people/INDEX.md", "memory/groups/INDEX.md"]
SECRET_HINT = re.compile(r"(password|api[_-]?key|token|secret|\bssn\b|card[_-]?number|cvv)", re.I)

class HomeMemory:
    def __init__(self, home: pathlib.Path | None = None):
        self.home = home or CONFIG.home
        for rel, body in TEMPLATES.items():
            p = self.home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(body, encoding="utf-8")
        (self.home / "workspace/your_files").mkdir(parents=True, exist_ok=True)
        (self.home / "memory/index").mkdir(parents=True, exist_ok=True)

    def read(self, rel: str) -> str:
        p = self.home / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def today_path(self) -> pathlib.Path:
        return self.home / "memory" / f"{date.today().isoformat()}.md"

    def read_today(self) -> str:
        p = self.today_path()
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def append_daily(self, text: str):
        if SECRET_HINT.search(text):
            raise ValueError("refusing to store a likely secret in memory; record that it exists and where it lives")
        p = self.today_path()
        with p.open("a", encoding="utf-8") as f:
            f.write(("" if p.exists() and p.stat().st_size else f"# {date.today().isoformat()}\n") + f"- {text.strip()}\n")

    def standing_files_section(self) -> str:
        parts = []
        for rel in STANDING_FILES:
            body = self.read(rel).strip()
            parts.append(f"<file path=\"~/{rel}\">\n{body}\n</file>")
        today = self.read_today().strip()
        parts.append(f"<file path=\"~/memory/{date.today().isoformat()}.md\">\n{today or '(empty)'}\n</file>")
        return "\n".join(parts)

    def files(self):
        yield self.home / "MEMORY.md"
        for p in sorted((self.home / "memory").rglob("*.md")):
            if "index" in p.parts:
                continue
            yield p

    def keyword_search(self, queries: list[str], max_results: int = 8) -> list[dict]:
        """Fallback until the vector index is wired: scores lines by query term overlap."""
        terms = {t.lower() for q in queries for t in re.findall(r"[a-z0-9]{3,}", q.lower())}
        hits = []
        for p in self.files():
            rel = p.relative_to(self.home).as_posix()
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                lw = line.lower()
                score = sum(1 for t in terms if t in lw)
                if score:
                    hits.append({"path": rel, "line": i, "citation": f"{rel}#L{i}",
                                 "score": round(score / max(len(terms), 1), 3), "text": line.strip()})
        hits.sort(key=lambda h: -h["score"])
        return hits[:max_results]

    def get(self, rel: str, from_line: int = 1, lines: int = 40) -> dict:
        p = self.home / rel
        if not p.exists():
            return {"error": f"{rel} not found"}
        all_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"path": rel, "from": from_line, "lines": all_lines[from_line - 1: from_line - 1 + lines],
                "total_lines": len(all_lines)}
