"""Credential vault: OAuth tokens encrypted at rest, one file per provider
under the agent's home. The agent never reads these; only connector code
running on its behalf does, and every use goes through a client that
refreshes and re-stores the token.

Key: SUPERAPP_VAULT_KEY (a Fernet key). Without it, a key is derived from
SUPERAPP_API_TOKEN for single-user dev, and failing that a key file is
generated once under ~/.superapp/vault.key.
"""
from __future__ import annotations
import base64, hashlib, json, os, pathlib
from cryptography.fernet import Fernet, InvalidToken
from ..config import CONFIG


def _key() -> bytes:
    if os.environ.get("SUPERAPP_VAULT_KEY"):
        return os.environ["SUPERAPP_VAULT_KEY"].encode()
    if os.environ.get("SUPERAPP_API_TOKEN"):
        return base64.urlsafe_b64encode(hashlib.sha256(os.environ["SUPERAPP_API_TOKEN"].encode()).digest())
    kp = pathlib.Path("~/.superapp/vault.key").expanduser()
    if not kp.exists():
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(Fernet.generate_key())
        kp.chmod(0o600)
    return kp.read_bytes().strip()


def _dir(home: pathlib.Path | None = None) -> pathlib.Path:
    d = (home or CONFIG.home) / ".vault"
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def store(provider: str, data: dict, home: pathlib.Path | None = None) -> None:
    p = _dir(home) / f"{provider}.enc"
    p.write_bytes(Fernet(_key()).encrypt(json.dumps(data).encode()))
    p.chmod(0o600)


def load(provider: str, home: pathlib.Path | None = None) -> dict | None:
    p = _dir(home) / f"{provider}.enc"
    if not p.exists():
        return None
    try:
        return json.loads(Fernet(_key()).decrypt(p.read_bytes()))
    except (InvalidToken, json.JSONDecodeError):
        return None


def delete(provider: str, home: pathlib.Path | None = None) -> bool:
    p = _dir(home) / f"{provider}.enc"
    if p.exists():
        p.unlink()
        return True
    return False


def providers(home: pathlib.Path | None = None) -> list[str]:
    return sorted(p.stem for p in _dir(home).glob("*.enc"))


def rekey(home: pathlib.Path, old_key: str) -> list[str]:
    """Re-encrypt every provider blob under this home from `old_key` to the current key (cell import)."""
    done = []
    for p in _dir(home).glob("*.enc"):
        try:
            data = json.loads(Fernet(old_key.encode()).decrypt(p.read_bytes()))
        except (InvalidToken, json.JSONDecodeError, ValueError):
            continue
        store(p.stem, data, home)
        done.append(p.stem)
    return done
