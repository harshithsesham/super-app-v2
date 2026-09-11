"""health-cli: the Apple Health command the apple-healthkit skill runs.

    health-cli status --provider healthkit [--start-date --end-date --check-missing-entries]
    health-cli query metrics --provider healthkit --start-date D [--end-date D] [--interval daily|weekly] [--fields a,b] [--list-fields]
    health-cli query sessions --provider healthkit --category sleep|workout --start-date D [--end-date D] [--fields a,b] [--list-categories] [--list-fields]
    health-cli query samples --provider healthkit --start-date D [--end-date D] [--start-time HH:MM] [--end-time HH:MM] [--fields t1,t2] [--limit n] [--format stdout|csv] [--output path] [--list-fields]
    health-cli auth connect|disconnect --provider healthkit
    health-cli backfill --provider healthkit --start-date D --end-date D

Reads what the phone synced into ~/.device/health/<provider>/; never contacts the device.
Output is JSON on stdout, exit 0 on success, 1 on a usage or data error.
"""
from __future__ import annotations
import csv, json, os, pathlib, sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from . import health

HOME = pathlib.Path(os.environ.get("HOME", "~")).expanduser()
METRIC_FIELDS = ["steps", "distance_meters", "active_energy_kcal", "basal_energy_kcal", "exercise_minutes", "flights_climbed",
                 "hr_average_bpm", "hr_min_bpm", "hr_max_bpm", "resting_hr_bpm", "hrv_sdnn_ms", "vo2max_ml_kg_min",
                 "respiratory_rate_bpm", "oxygen_saturation_pct", "body_mass_kg", "stand_hours", "sleep_minutes"]
SESSION_FIELDS = {
    "sleep": ["id", "start_datetime", "end_datetime", "timezone", "duration_minutes", "in_bed_minutes", "asleep_minutes", "core_minutes",
              "deep_minutes", "rem_minutes", "awake_minutes", "awakenings", "efficiency_pct", "source"],
    "workout": ["id", "start_datetime", "end_datetime", "timezone", "activity_type", "duration_minutes", "energy_kcal", "distance_meters",
                "hr_average_bpm", "average_speed_mps", "elevation_gain_meters", "is_indoor", "source"],
}
INSTRUCTION = ("Apple Health syncs from the phone, not from an account. On the iPhone: open the app, Connectors, Apple Health, "
               "allow access; the app syncs the last 30 days and keeps syncing whenever it is opened.")


def out(obj, code: int = 0):
    print(json.dumps(obj, indent=1, default=str))
    sys.exit(code)


def parse(argv: list[str]) -> tuple[list[str], dict]:
    pos, opts = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            k = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[k] = argv[i + 1]; i += 2
            else:
                opts[k] = True; i += 1
        else:
            pos.append(a); i += 1
    return pos, opts


def provider_of(opts: dict) -> str:
    p = opts.get("provider")
    if not p or p not in health.PROVIDERS:
        out({"ok": False, "error": "usage", "message": f"--provider is required; one of {', '.join(health.PROVIDERS)}"}, 1)
    return str(p)


def _window(opts: dict) -> list[str]:
    if not opts.get("start-date"):
        out({"ok": False, "error": "usage", "message": "--start-date <YYYY-MM-DD> is required"}, 1)
    try:
        return health.date_range(str(opts["start-date"]), str(opts["end-date"]) if opts.get("end-date") else None)
    except ValueError as e:
        out({"ok": False, "error": "usage", "message": f"bad date: {e}"}, 1)


def _pick(row: dict, fields: list[str] | None, always: tuple[str, ...]) -> dict:
    if not fields:
        return row
    return {k: v for k, v in row.items() if k in fields or k in always}


# ---------------------------------------------------------------- status --
def cmd_status(opts: dict):
    p = provider_of(opts)
    st = health.status(HOME, p)
    if not st["synced"]:
        st.update({"requires_connect": False, "auth_type": "device_sync", "instruction": INSTRUCTION,
                   "message": "Nothing synced from the device yet."})
    if opts.get("check-missing-entries"):
        days = _window(opts)
        cov = health.coverage(HOME, p, days)
        st["unsynced_dates"] = cov["missing_dates"]
        st["coverage"] = cov
    out(st)


# --------------------------------------------------------------- metrics --
def cmd_metrics(opts: dict):
    p = provider_of(opts)
    rows = health.metrics(HOME, p)
    if opts.get("list-fields"):
        seen = defaultdict(int)
        for r in rows:
            for k, v in r.items():
                if k != "date" and v is not None:
                    seen[k] += 1
        names = list(dict.fromkeys(METRIC_FIELDS + sorted(seen)))
        out({"ok": True, "provider": p, "category": "daily-metrics", "observed_count": len(rows),
             "fields": [{"name": n, "observed": seen.get(n, 0) > 0, **({"count": seen[n]} if seen.get(n) else {})} for n in names]})
    days = _window(opts)
    fields = [f.strip() for f in str(opts.get("fields", "")).split(",") if f.strip()] or None
    interval = str(opts.get("interval", "daily"))
    by_date = {r["date"]: r for r in rows}
    picked = [dict(by_date[d], record_count=1) for d in days if d in by_date]
    if interval == "weekly":
        weeks: dict[str, list[dict]] = defaultdict(list)
        for r in picked:
            d = date.fromisoformat(r["date"]); weeks[(d - timedelta(days=d.weekday())).isoformat()].append(r)
        agg = []
        for ws, rs in sorted(weeks.items()):
            row: dict = {"week_start": ws, "record_count": len(rs)}
            for k in set().union(*(r.keys() for r in rs)) - {"date", "record_count"}:
                vals = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
                if not vals:
                    continue
                row[k] = round(sum(vals), 2) if k in ("steps", "distance_meters", "active_energy_kcal", "basal_energy_kcal", "exercise_minutes",
                                                      "flights_climbed", "sleep_minutes", "stand_hours") else round(sum(vals) / len(vals), 2)
            agg.append(row)
        picked = agg
    elif interval == "hourly":
        out({"ok": False, "error": "unsupported", "message": "hourly buckets are not synced; use query samples for intraday data"}, 1)
    records = [_pick(r, fields, ("date", "week_start", "record_count")) for r in picked]
    out({"ok": True, "provider": p, "category": "daily-metrics", "interval": interval, "coverage": health.coverage(HOME, p, days), "records": records})


# -------------------------------------------------------------- sessions --
def cmd_sessions(opts: dict):
    p = provider_of(opts)
    if opts.get("list-categories"):
        out({"ok": True, "provider": p, "categories": list(SESSION_FIELDS)})
    cat = str(opts.get("category", ""))
    if cat not in SESSION_FIELDS:
        out({"ok": False, "error": "usage", "message": "--category sleep|workout is required"}, 1)
    if opts.get("list-fields"):
        out({"ok": True, "provider": p, "category": cat, "fields": SESSION_FIELDS[cat]})
    days = _window(opts)
    lo, hi = days[0], days[-1]
    fields = [f.strip() for f in str(opts.get("fields", "")).split(",") if f.strip()] or None
    rows = [s for s in health.sessions(HOME, p) if s.get("category") == cat and lo <= str(s.get("end_datetime", ""))[:10] and str(s.get("start_datetime", ""))[:10] <= hi]
    rows.sort(key=lambda s: s.get("start_datetime", ""))
    out({"ok": True, "provider": p, "category": cat, "coverage": health.coverage(HOME, p, days),
         "records": [_pick(r, fields, ("id", "start_datetime", "end_datetime", "timezone")) for r in rows]})


# --------------------------------------------------------------- samples --
def cmd_samples(opts: dict):
    p = provider_of(opts)
    rows = health.samples(HOME, p)
    if opts.get("list-fields"):
        counts = defaultdict(int)
        for r in rows:
            counts[r.get("type", "?")] += 1
        out({"ok": True, "provider": p, "fields": [{"name": t, "observed": True, "count": n} for t, n in sorted(counts.items())]})
    days = _window(opts)
    lo = f"{days[0]}T{opts.get('start-time', '00:00')}"
    hi = f"{days[-1]}T{opts.get('end-time', '23:59:59')}"
    types = {f.strip() for f in str(opts.get("fields", "")).split(",") if f.strip()}
    sel = [r for r in rows if (not types or r.get("type") in types) and lo <= str(r.get("datetime", ""))[:19] <= hi]
    sel.sort(key=lambda r: (r.get("type", ""), r.get("datetime", "")))
    limit = int(opts.get("limit", 2000))
    total = len(sel)
    sel = sel[:limit]
    if opts.get("output"):
        path = pathlib.Path(str(opts["output"])).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f); w.writerow(["type", "datetime", "value", "unit"])
            for r in sel:
                w.writerow([r.get("type"), r.get("datetime"), r.get("value"), r.get("unit")])
        out({"ok": True, "provider": p, "written": str(path), "rows": len(sel), "total_matching": total, "types": sorted({r.get("type") for r in sel})})
    if opts.get("format") == "csv":
        w = csv.writer(sys.stdout); w.writerow(["type", "datetime", "value", "unit"])
        for r in sel:
            w.writerow([r.get("type"), r.get("datetime"), r.get("value"), r.get("unit")])
        sys.exit(0)
    out({"ok": True, "provider": p, "count": len(sel), "total_matching": total, "records": sel})


# ------------------------------------------------------------------ auth --
def cmd_auth(pos: list[str], opts: dict):
    p = provider_of(opts)
    out({"ok": True, "provider": p, "auth_type": "device_sync", "requires_connect": False, "instruction": INSTRUCTION,
         "synced": health.status(HOME, p)["synced"]})


def cmd_backfill(opts: dict):
    p = provider_of(opts)
    days = _window(opts)
    req = health.request_backfill(HOME, p, days[0], days[-1])
    # the daemon turns queued requests into a push and the app syncs the range on its next open
    try:
        import httpx
        httpx.post(os.environ.get("SUPERAPP_INTERNAL_URL", "http://127.0.0.1:18792").rstrip("/") + "/internal/health/backfill",
                   json={"home": str(HOME), "provider": p, "request": req},
                   headers={"X-Internal-Token": os.environ.get("SUPERAPP_INTERNAL_TOKEN", "")}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    out({"ok": True, "provider": p, "queued": req, "message": "Asked the phone to sync this range. It happens the next time the app opens "
         "(a notification asks the user to open it); re-run the query afterwards."})


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    pos, opts = parse(argv)
    if not pos or opts.get("help") or pos[0] in ("--help", "-h"):
        out({"usage": __doc__})
    cmd = pos[0]
    if cmd == "status":
        cmd_status(opts)
    elif cmd == "query" and len(pos) > 1:
        {"metrics": cmd_metrics, "sessions": cmd_sessions, "samples": cmd_samples}.get(pos[1], lambda o: out({"ok": False, "error": "usage", "message": "query metrics|sessions|samples"}, 1))(opts)
    elif cmd == "auth":
        cmd_auth(pos[1:], opts)
    elif cmd == "backfill":
        cmd_backfill(opts)
    else:
        out({"ok": False, "error": "usage", "message": __doc__}, 1)


if __name__ == "__main__":
    main()
