"""Device-synced health data (Apple HealthKit today), stored per user under
~/.device/health/<provider>/ as JSON lines the phone app uploads:

  metrics.jsonl    one row per local date: {"date", "steps", "distance_meters", ...}
  sessions.jsonl   sleep and workout sessions: {"id", "category", "start_datetime", "end_datetime", ...}
  samples.jsonl    raw points: {"type", "datetime", "value", "unit"}
  meta.json        device, last sync, provider

Rows are keyed (date / id / type+datetime) so a re-sync of a range overwrites
rather than duplicates. health-cli reads these; the daemon's /v1/health/sync
writes them.
"""
from __future__ import annotations
import json, pathlib, time
from datetime import date, datetime, timedelta

PROVIDERS = ("healthkit",)


def root(home: pathlib.Path, provider: str) -> pathlib.Path:
    p = home / ".device" / "health" / provider
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(p: pathlib.Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write(p: pathlib.Path, rows: list[dict]):
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)


def _merge(p: pathlib.Path, rows: list[dict], key):
    cur = {key(r): r for r in _read(p) if key(r) is not None}
    for r in rows:
        k = key(r)
        if k is not None:
            cur[k] = {**cur.get(k, {}), **r}
    _write(p, sorted(cur.values(), key=lambda r: str(key(r))))
    return len(cur)


def ingest(home: pathlib.Path, provider: str, payload: dict) -> dict:
    """A sync batch from the phone. Returns the counts now on disk."""
    d = root(home, provider)
    n_metrics = _merge(d / "metrics.jsonl", payload.get("metrics") or [], lambda r: r.get("date"))
    n_sessions = _merge(d / "sessions.jsonl", payload.get("sessions") or [], lambda r: r.get("id"))
    n_samples = _merge(d / "samples.jsonl", payload.get("samples") or [], lambda r: (r.get("type"), r.get("datetime")) if r.get("type") and r.get("datetime") else None)
    meta = read_meta(home, provider)
    meta.update({"provider": provider, "device": payload.get("device") or meta.get("device") or {},
                 "last_synced_at": time.time(), "timezone": payload.get("timezone") or meta.get("timezone"),
                 "last_range": payload.get("range") or meta.get("last_range")})
    fulfilled = set(payload.get("fulfills") or [])
    if fulfilled:
        meta["requests"] = [r for r in meta.get("requests", []) if r["id"] not in fulfilled]
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return {"metrics": n_metrics, "sessions": n_sessions, "samples": n_samples}


def read_meta(home: pathlib.Path, provider: str) -> dict:
    p = root(home, provider) / "meta.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def request_backfill(home: pathlib.Path, provider: str, start: str, end: str) -> dict:
    """The agent wants a range the phone has not synced: queue it for the app's next sync."""
    meta = read_meta(home, provider)
    req = {"id": f"bf_{int(time.time())}", "start_date": start, "end_date": end, "requested_at": time.time()}
    meta.setdefault("requests", []).append(req)
    meta["requests"] = meta["requests"][-10:]
    (root(home, provider) / "meta.json").write_text(json.dumps(meta, indent=1))
    return req


def metrics(home: pathlib.Path, provider: str) -> list[dict]:
    return _read(root(home, provider) / "metrics.jsonl")


def sessions(home: pathlib.Path, provider: str) -> list[dict]:
    return _read(root(home, provider) / "sessions.jsonl")


def samples(home: pathlib.Path, provider: str) -> list[dict]:
    return _read(root(home, provider) / "samples.jsonl")


def status(home: pathlib.Path, provider: str) -> dict:
    meta = read_meta(home, provider)
    ms, ss, sm = metrics(home, provider), sessions(home, provider), samples(home, provider)
    cats = []
    if ms:
        cats.append({"name": "daily-metrics", "record_count": len(ms), "earliest_datetime": ms[0]["date"], "latest_datetime": ms[-1]["date"]})
    for cat in ("sleep", "workout"):
        rows = [s for s in ss if s.get("category") == cat]
        if rows:
            cats.append({"name": cat, "record_count": len(rows), "earliest_datetime": min(r["start_datetime"] for r in rows),
                         "latest_datetime": max(r["end_datetime"] for r in rows)})
    if sm:
        cats.append({"name": "samples", "record_count": len(sm), "earliest_datetime": min(r["datetime"] for r in sm),
                     "latest_datetime": max(r["datetime"] for r in sm)})
    return {"ok": True, "provider": provider, "synced": bool(meta.get("last_synced_at")), "device": meta.get("device") or {},
            "last_synced_at": meta.get("last_synced_at"), "timezone": meta.get("timezone"), "categories": cats,
            "pending_requests": meta.get("requests", [])}


def date_range(start: str, end: str | None) -> list[str]:
    a = date.fromisoformat(start)
    b = date.fromisoformat(end) if end else date.today()
    if b < a:
        a, b = b, a
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def coverage(home: pathlib.Path, provider: str, days: list[str]) -> dict:
    have = {r["date"] for r in metrics(home, provider)}
    missing = [d for d in days if d not in have]
    out = {"complete": not missing, "requested_days": len(days), "synced_days": len(days) - len(missing), "missing_dates": missing[:31]}
    if missing:
        out["warning"] = (f"{len(missing)} of {len(days)} days are not synced from the device. Run "
                          f"`health-cli backfill --provider {provider} --start-date {missing[0]} --end-date {missing[-1]}` "
                          "to ask the phone for them, then re-query.")
        out["backfill_data_source"] = {"start_date": missing[0], "end_date": missing[-1]}
    return out
