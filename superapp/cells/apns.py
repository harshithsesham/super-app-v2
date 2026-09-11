"""Apple Push Notification service client for the gateway.

Token-based auth: a JWT signed with the .p8 key (ES256), refreshed hourly, sent
over HTTP/2 to api.push.apple.com (or the sandbox host for development builds).
No third-party push relay: the device token goes from the phone to our gateway
and nowhere else.

Env: APNS_KEY_P8 (the key file contents), APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID.
Without them, send() logs what it would have sent and returns "dry_run".
"""
from __future__ import annotations
import base64, json, os, threading, time
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class APNs:
    def __init__(self):
        self.key_pem = os.environ.get("APNS_KEY_P8", "").replace("\\n", "\n")
        self.key_id = os.environ.get("APNS_KEY_ID", "")
        self.team_id = os.environ.get("APNS_TEAM_ID", "")
        self.bundle_id = os.environ.get("APNS_BUNDLE_ID", "com.harshith.superapp")
        self._key = serialization.load_pem_private_key(self.key_pem.encode(), password=None) if self.key_pem else None
        self._jwt: tuple[float, str] | None = None
        self._lock = threading.Lock()
        self._clients: dict[str, httpx.Client] = {}

    def configured(self) -> bool:
        return bool(self._key and self.key_id and self.team_id)

    def token(self) -> str:
        """Provider token, reused for 50 minutes (Apple allows up to an hour)."""
        with self._lock:
            if self._jwt and time.time() - self._jwt[0] < 3000:
                return self._jwt[1]
            header = _b64(json.dumps({"alg": "ES256", "kid": self.key_id}).encode())
            claims = _b64(json.dumps({"iss": self.team_id, "iat": int(time.time())}).encode())
            signing = f"{header}.{claims}".encode()
            der = self._key.sign(signing, ec.ECDSA(hashes.SHA256()))
            r, s = decode_dss_signature(der)
            raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
            jwt = f"{header}.{claims}.{_b64(raw)}"
            self._jwt = (time.time(), jwt)
            return jwt

    def _client(self, env: str) -> httpx.Client:
        if env not in self._clients:
            self._clients[env] = httpx.Client(base_url=HOSTS[env], http2=True, timeout=15)
        return self._clients[env]

    def send(self, device_token: str, env: str, title: str, body: str, data: dict | None = None,
             thread_id: str | None = None) -> str:
        """Returns 'ok', 'dry_run', 'gone' (unregister this token), or an error string."""
        payload = {"aps": {"alert": {"title": title[:80], "body": body[:400]}, "sound": "default",
                           **({"thread-id": thread_id} if thread_id else {})}, **(data or {})}
        if not self.configured():
            print(f"push: dry run ({env}) {device_token[:8]}… {title!r}: {body[:60]!r}", flush=True)
            return "dry_run"
        env = env if env in HOSTS else "production"
        r = self._client(env).post(f"/3/device/{device_token}", json=payload, headers={
            "authorization": f"bearer {self.token()}", "apns-topic": self.bundle_id, "apns-push-type": "alert",
            "apns-priority": "10", "apns-expiration": str(int(time.time()) + 3600)})
        if r.status_code == 200:
            return "ok"
        reason = (r.json().get("reason") if r.content else "") or str(r.status_code)
        if r.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
            return "gone"
        if reason in ("ExpiredProviderToken", "InvalidProviderToken"):
            self._jwt = None
        return f"error: {r.status_code} {reason}"
