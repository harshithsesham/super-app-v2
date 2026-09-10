"""The agent's voice: ElevenLabs text-to-speech, cached on disk by content
hash. Same voice as the earlier app by default ("George"). No key means no
audio, and the orb falls back to showing text.

Env: SUPERAPP_ELEVENLABS_API_KEY, SUPERAPP_VOICE_ID, SUPERAPP_ELEVENLABS_MODEL
"""
from __future__ import annotations
import hashlib, os, pathlib
import httpx

DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"


def configured() -> bool:
    return bool(os.environ.get("SUPERAPP_ELEVENLABS_API_KEY"))


def voice_id() -> str:
    return os.environ.get("SUPERAPP_VOICE_ID", DEFAULT_VOICE)


def tts(text: str, cache_dir: pathlib.Path) -> bytes:
    if not configured() or not text.strip():
        return b""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice_id()}:{text}".encode()).hexdigest()[:32]
    p = cache_dir / f"{key}.mp3"
    if p.exists():
        return p.read_bytes()
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id()}",
                   headers={"xi-api-key": os.environ["SUPERAPP_ELEVENLABS_API_KEY"]},
                   json={"text": text[:2500], "model_id": os.environ.get("SUPERAPP_ELEVENLABS_MODEL", "eleven_multilingual_v2"),
                         "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.25}},
                   timeout=60)
    if r.status_code != 200:
        return b""
    p.write_bytes(r.content)
    return r.content
