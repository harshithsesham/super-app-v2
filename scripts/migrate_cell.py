"""Move one user from the shared daemon on the AWS box into their cell behind the gateway.

Exports from the box over ssh (home directory, Postgres dump, sign-in sessions, old
vault key), then posts the sessions to the gateway and the bundle to the user's
cell through the gateway. The old daemon keeps running; nothing is deleted.

    ./.venv/bin/python scripts/migrate_cell.py --user harshithsesham007 \
        --ssh ubuntu@3.17.83.242 --key ~/.ssh/superapp.pem \
        --gateway https://muse-gateway.fly.dev --internal-token "$SUPERAPP_INTERNAL_TOKEN"

Run it yourself: it handles the vault key and the internal token.
"""
from __future__ import annotations
import argparse, io, json, os, subprocess, tarfile, time
import httpx


def ssh(a, cmd: str, binary: bool = False):
    r = subprocess.run(["ssh", "-i", os.path.expanduser(a.key), a.ssh, cmd], capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--ssh", required=True)
    ap.add_argument("--key", default="~/.ssh/superapp.pem")
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--internal-token", default=os.environ.get("SUPERAPP_INTERNAL_TOKEN", ""))
    ap.add_argument("--daemon", default="muse-daemon")
    ap.add_argument("--db-container", default="deploy-db-1")
    ap.add_argument("--skip-sessions", action="store_true")
    a = ap.parse_args()
    hdr = {"X-Internal-Token": a.internal_token}
    dbname = "muse_" + "".join(c if c.isalnum() or c == "_" else "_" for c in a.user.lower())[:40]

    print("exporting sessions, home, database, vault key from the box ...")
    sessions = ssh(a, f"docker exec {a.daemon} cat /data/users/.sessions.json")
    home_tar = ssh(a, f"docker exec {a.daemon} tar czf - -C /data/users {a.user}", binary=True)
    dump = ssh(a, f"docker exec {a.db_container} pg_dump -U superapp --no-owner --no-acl {dbname}")
    vault_key = ssh(a, "grep '^SUPERAPP_VAULT_KEY=' /opt/super-app/.env /opt/super-app-v2/.env 2>/dev/null | tail -1 | cut -d= -f2-").strip()
    print(f"  home tar {len(home_tar)//1024} KB, dump {len(dump)//1024} KB, vault key {'found' if vault_key else 'missing'}")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as out:
        with tarfile.open(fileobj=io.BytesIO(home_tar), mode="r:gz") as src:
            for m in src.getmembers():
                m.name = "home/" + m.name.split("/", 1)[1] if "/" in m.name else "home"
                if m.name == "home":
                    continue
                out.addfile(m, src.extractfile(m) if m.isfile() else None)
        for name, data in (("db.sql", dump.encode()), ("meta.json", json.dumps({"vault_key_old": vault_key}).encode())):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime = len(data), int(time.time())
            out.addfile(ti, io.BytesIO(data))
    bundle = buf.getvalue()

    if not a.skip_sessions:
        r = httpx.post(f"{a.gateway}/internal/sessions/import", json=json.loads(sessions), headers=hdr, timeout=60)
        print("sessions:", r.status_code, r.text[:200])
    print(f"importing {len(bundle)//1024} KB into the cell (creates and boots it on first use) ...")
    r = httpx.post(f"{a.gateway}/internal/cells/{a.user}/import", content=bundle, headers=hdr, timeout=900)
    print("import:", r.status_code, r.text[:400])
    time.sleep(3)
    r = httpx.get(f"{a.gateway}/internal/cells", headers=hdr, timeout=30)
    print("fleet:", r.text[:400])


if __name__ == "__main__":
    main()
