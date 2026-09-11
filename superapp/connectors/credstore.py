"""The Secure Store: website logins and API keys the user typed on a secure entry
page, encrypted at rest in the cell's vault. The agent only ever sees metadata;
the browser worker fills values into pages on its behalf.

  .vault/credentials/<id>.enc           Fernet-encrypted JSON {kind, site, page_url, fields{...}, updated_at}
  .vault/credential_requests.json       open and past entry-card requests (no secrets)
"""
from __future__ import annotations
import hashlib, json, pathlib, time, urllib.parse
from cryptography.fernet import Fernet, InvalidToken
from . import vault


def site_of(url: str) -> str:
    host = urllib.parse.urlsplit(url if "://" in url else "https://" + url).netloc.lower()
    return host.split("@")[-1].split(":")[0]


def _dir(home: pathlib.Path) -> pathlib.Path:
    d = home / ".vault" / "credentials"
    d.mkdir(parents=True, exist_ok=True)
    try:
        (home / ".vault").chmod(0o700)
    except OSError:
        pass
    return d


def entry_id(kind: str, site: str) -> str:
    return "cred_" + hashlib.sha1(f"{kind}|{site}".encode()).hexdigest()[:12]


def save(home: pathlib.Path, kind: str, site: str, page_url: str, fields: dict[str, str], label: str | None = None) -> dict:
    """Store (or replace) the entry for this site and kind. Values never leave this module except through `secret()`."""
    eid = entry_id(kind, site)
    rec = {"id": eid, "kind": kind, "site": site, "page_url": page_url, "label": label or site,
           "fields": {k: v for k, v in fields.items() if v}, "updated_at": time.time()}
    p = _dir(home) / f"{eid}.enc"
    p.write_bytes(Fernet(vault._key()).encrypt(json.dumps(rec).encode()))
    p.chmod(0o600)
    return public(rec)


def public(rec: dict) -> dict:
    return {"id": rec["id"], "kind": rec["kind"], "site": rec["site"], "page_url": rec.get("page_url"), "label": rec.get("label"),
            "fields": sorted(rec.get("fields", {}).keys()), "updated_at": rec.get("updated_at"), "available": True}


def _load(p: pathlib.Path) -> dict | None:
    try:
        return json.loads(Fernet(vault._key()).decrypt(p.read_bytes()))
    except (InvalidToken, json.JSONDecodeError, OSError):
        return None


def list_entries(home: pathlib.Path, domain: str | None = None) -> list[dict]:
    want = site_of(domain) if domain else None
    out = []
    for p in sorted(_dir(home).glob("*.enc")):
        rec = _load(p)
        if rec and (not want or rec["site"] == want or rec["site"].endswith("." + want) or want.endswith("." + rec["site"])):
            out.append(public(rec))
    return out


def secret(home: pathlib.Path, site: str, kind: str = "login") -> dict | None:
    """Full record with values. Only the browser worker's fill step calls this; the model never does."""
    want = site_of(site)
    for cand in (want, *[want.split(".", i)[-1] for i in range(1, want.count("."))]):
        rec = _load(_dir(home) / f"{entry_id(kind, cand)}.enc")
        if rec:
            return rec
    for p in _dir(home).glob("*.enc"):   # subdomain saved, base domain asked for
        rec = _load(p)
        if rec and rec["kind"] == kind and (rec["site"].endswith("." + want) or want.endswith("." + rec["site"])):
            return rec
    return None


def delete(home: pathlib.Path, eid: str) -> bool:
    p = _dir(home) / f"{eid}.enc"
    if p.exists():
        p.unlink()
        return True
    return False


# ---------------------------------------------------------------- requests --
def _req_path(home: pathlib.Path) -> pathlib.Path:
    (home / ".vault").mkdir(parents=True, exist_ok=True)
    return home / ".vault" / "credential_requests.json"


def requests(home: pathlib.Path) -> list[dict]:
    p = _req_path(home)
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except json.JSONDecodeError:
        return []


def _save_requests(home: pathlib.Path, rows: list[dict]):
    _req_path(home).write_text(json.dumps(rows[-100:], indent=1))


def new_request(home: pathlib.Path, kind: str, page_url: str, extra: dict | None = None) -> dict:
    site = site_of(page_url)
    rows = requests(home)
    for r in rows:
        if r["status"] == "pending" and r["site"] == site and r["kind"] == kind and time.time() - r["created_at"] < 3600:
            return dict(r, already_sent=True)
    rid = f"req_{hashlib.sha1(f'{kind}|{site}|{time.time()}'.encode()).hexdigest()[:10]}"
    req = {"id": rid, "kind": kind, "site": site, "page_url": page_url, "status": "pending", "created_at": time.time(),
           "embed_token": f"[[secure-store:{rid}]]", **(extra or {})}
    rows.append(req)
    _save_requests(home, rows)
    return req


def get_request(home: pathlib.Path, rid: str) -> dict | None:
    return next((r for r in requests(home) if r["id"] == rid), None)


def update_request(home: pathlib.Path, rid: str, **changes) -> dict | None:
    rows = requests(home)
    for r in rows:
        if r["id"] == rid:
            r.update(changes)
            _save_requests(home, rows)
            return r
    return None
