"""Build the Skills section: a short catalog the model scans, pointing at the
full SKILL.md playbooks it reads on demand with `muse.read`.
"""
from __future__ import annotations
import pathlib, re
import yaml
from ..config import CONFIG

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _frontmatter(p: pathlib.Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace")
    m = _FM.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


# skill directory -> vault provider whose presence means "connected"
PROVIDER_FOR_SKILL = {"gmail": "gmail", "google-calendar": "google_calendar", "apple-healthkit": "apple_healthkit"}


def catalog(home: pathlib.Path | None = None) -> list[dict]:
    from ..connectors import vault
    connected = set(vault.providers(home or CONFIG.home))
    if "gmail" in connected:   # Calendar shares the Google sign-in and counts as connected once its scope is granted
        from ..connectors.gmail import CALENDAR_SCOPE
        tok = vault.load("gmail", home or CONFIG.home) or {}
        if CALENDAR_SCOPE in (tok.get("scopes") or []):
            connected.add("google_calendar")
    try:
        from ..connectors import health as _health
        if _health.status(home or CONFIG.home, "healthkit")["synced"]:
            connected.add("apple_healthkit")
    except Exception:  # noqa: BLE001
        pass
    # status is keyed on the skill directory so every connector skill gets one, listed in skills.yaml or not
    statuses = {d: ("connected" if p in connected else "available") for d, p in PROVIDER_FOR_SKILL.items()}
    out = []
    for skill_md in sorted(CONFIG.skills_dir.rglob("SKILL.md")):
        rel = skill_md.parent.relative_to(CONFIG.skills_dir).as_posix()
        fm = _frontmatter(skill_md)
        if fm.get("metadata", {}).get("includeInPrompt") is False:
            continue
        name = str(fm.get("name") or rel).strip('"')
        desc = str(fm.get("description") or "").strip().replace("\n", " ")
        out.append({"name": name, "path": str(skill_md), "status": statuses.get(rel.split("/")[0], "available"),
                    "description": desc[:200]})
    return out


def section(home: pathlib.Path | None = None) -> str:
    lines = ["# Skills",
             "Skills are reproducible playbooks for a specific product, service, or task. Before a task that "
             "involves a product, service, or reusable workflow, find the matching skill below and read its "
             "SKILL.md with `muse.read` (absolute path given), then follow it exactly. Resolve relative paths "
             "against the skill's own directory. A skill marked `available` documents a connector that is not "
             "connected yet; check connection state live before treating it as connected."]
    for s in catalog(home):
        lines.append(f"- `{s['name']}` ({s['status']}): {s['description']} — `{s['path']}`")
    return "\n".join(lines)
