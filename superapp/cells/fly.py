"""A small client for the Fly Machines API (https://fly.io/docs/machines/api/).

Only what the gateway needs: volumes, machines, start/stop/wait. FLY_API_BASE can
point at scripts/fake_fly.py, which backs the same endpoints with local Docker
containers so the whole cell flow runs on a laptop.
"""
from __future__ import annotations
import os, time
import httpx


class FlyError(RuntimeError):
    pass


class FlyMachines:
    def __init__(self, token: str | None = None, app: str | None = None, base: str | None = None):
        self.token = token or os.environ.get("FLY_API_TOKEN", "")
        self.app = app or os.environ.get("FLY_CELLS_APP", "muse-cells")
        self.base = (base or os.environ.get("FLY_API_BASE", "https://api.machines.dev")).rstrip("/")
        self.http = httpx.Client(base_url=f"{self.base}/v1/apps/{self.app}", timeout=httpx.Timeout(90, connect=15),
                                 headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})

    def _call(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 300:
            raise FlyError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def create_volume(self, name: str, region: str, size_gb: int) -> dict:
        return self._call("POST", "/volumes", json={"name": name, "region": region, "size_gb": size_gb, "encrypted": True})

    def create_machine(self, region: str, config: dict, name: str | None = None) -> dict:
        body = {"region": region, "config": config}
        if name:
            body["name"] = name
        return self._call("POST", "/machines", json=body)

    def get(self, machine_id: str) -> dict:
        return self._call("GET", f"/machines/{machine_id}")

    def start(self, machine_id: str) -> dict:
        return self._call("POST", f"/machines/{machine_id}/start")

    def stop(self, machine_id: str) -> dict:
        return self._call("POST", f"/machines/{machine_id}/stop")

    def destroy(self, machine_id: str) -> dict:
        return self._call("DELETE", f"/machines/{machine_id}", params={"force": "true"})

    def wait(self, machine_id: str, state: str = "started", timeout: int = 60) -> dict:
        return self._call("GET", f"/machines/{machine_id}/wait", params={"state": state, "timeout": timeout})

    def state(self, machine_id: str) -> str:
        return self.get(machine_id).get("state", "unknown")

    def wait_state(self, machine_id: str, state: str, timeout: int = 60) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.state(machine_id)
            if s == state:
                return s
            time.sleep(1)
        raise FlyError(f"machine {machine_id} did not reach {state} in {timeout}s")
