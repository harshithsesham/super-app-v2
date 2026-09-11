"""A stand-in for the Fly Machines API backed by local Docker, so the gateway's
cell flow (create volume + machine, start, stop, wait, wake) runs on a laptop.

    ./.venv/bin/python scripts/fake_fly.py --port 18795 --network cells

Machines are containers on the given Docker network; `private_ip` is the
container's address there, so run the gateway on the same network with
FLY_CELL_ADDR_TEMPLATE=http://{private_ip}:18792.
"""
from __future__ import annotations
import argparse, json, secrets, subprocess, time
from fastapi import FastAPI, HTTPException, Request
import uvicorn

app = FastAPI()
MACHINES: dict[str, dict] = {}
VOLUMES: dict[str, dict] = {}
NETWORK = "cells"


def sh(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.strip()


def _state(mid: str) -> str:
    try:
        return "started" if sh("inspect", "-f", "{{.State.Running}}", f"flym-{mid}") == "true" else "stopped"
    except subprocess.CalledProcessError:
        return "destroyed"


def _ip(mid: str) -> str:
    return sh("inspect", "-f", "{{(index .NetworkSettings.Networks \"%s\").IPAddress}}" % NETWORK, f"flym-{mid}")


def _view(mid: str) -> dict:
    m = MACHINES[mid]
    st = _state(mid)
    return {"id": mid, "name": m["name"], "state": st, "region": m["region"], "private_ip": _ip(mid) if st == "started" else m.get("private_ip", ""),
            "config": m["config"]}


@app.post("/v1/apps/{fly_app}/volumes")
async def create_volume(fly_app: str, req: Request):
    body = await req.json()
    vid = "vol_" + secrets.token_hex(6)
    sh("volume", "create", f"flyvol-{vid}")
    VOLUMES[vid] = {"id": vid, "name": body["name"], "size_gb": body.get("size_gb", 1), "region": body.get("region")}
    return VOLUMES[vid]


@app.post("/v1/apps/{fly_app}/machines")
async def create_machine(fly_app: str, req: Request):
    body = await req.json()
    cfg = body["config"]
    mid = secrets.token_hex(7)
    args = ["run", "-d", "--name", f"flym-{mid}", "--network", NETWORK, "--label", f"fly_app={fly_app}",
            "--memory", f"{cfg.get('guest', {}).get('memory_mb', 2048)}m"]
    for mnt in cfg.get("mounts", []):
        args += ["-v", f"flyvol-{mnt['volume']}:{mnt['path']}"]
    for k, v in cfg.get("env", {}).items():
        args += ["-e", f"{k}={v}"]
    args.append(cfg["image"])
    sh(*args)
    MACHINES[mid] = {"name": body.get("name") or mid, "region": body.get("region"), "config": cfg}
    time.sleep(0.5)
    MACHINES[mid]["private_ip"] = _ip(mid)
    return _view(mid)


@app.get("/v1/apps/{fly_app}/machines/{mid}")
def get_machine(fly_app: str, mid: str):
    if mid not in MACHINES:
        raise HTTPException(404, "no such machine")
    return _view(mid)


@app.post("/v1/apps/{fly_app}/machines/{mid}/start")
def start(fly_app: str, mid: str):
    sh("start", f"flym-{mid}")
    time.sleep(0.5)
    MACHINES[mid]["private_ip"] = _ip(mid)
    return {"ok": True, "previous_state": "stopped"}


@app.post("/v1/apps/{fly_app}/machines/{mid}/stop")
def stop(fly_app: str, mid: str):
    sh("stop", "-t", "20", f"flym-{mid}")
    return {"ok": True}


@app.delete("/v1/apps/{fly_app}/machines/{mid}")
def destroy(fly_app: str, mid: str):
    sh("rm", "-f", f"flym-{mid}")
    MACHINES.pop(mid, None)
    return {"ok": True}


@app.get("/v1/apps/{fly_app}/machines/{mid}/wait")
def wait(fly_app: str, mid: str, state: str = "started", timeout: int = 60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _state(mid) == state:
            return {"ok": True}
        time.sleep(0.5)
    raise HTTPException(408, f"timeout waiting for {state}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18795)
    ap.add_argument("--network", default="cells")
    a = ap.parse_args()
    NETWORK = a.network
    subprocess.run(["docker", "network", "create", NETWORK], capture_output=True)
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")
