"""Runtime configuration.

Values come from config/home.yaml (ported from Muse's home.yaml) plus a few
environment variables for secrets and paths:

  META_API_KEY      Meta Model API key (required to run)
  MODEL_API_BASE    default https://api.meta.ai/v1
  MODEL             default meta/muse-spark-1.3
  SUPERAPP_HOME     the agent's home directory (per user), default ~/.superapp/home
"""
from __future__ import annotations
import contextvars, os, pathlib
from dataclasses import dataclass, field

_HOME: contextvars.ContextVar[pathlib.Path | None] = contextvars.ContextVar("superapp_home", default=None)
import yaml
from dotenv import load_dotenv

REPO = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

def _load_yaml(p: pathlib.Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

@dataclass
class Config:
    home_yaml: dict = field(default_factory=lambda: _load_yaml(REPO / "config/home.yaml"))
    skills_yaml: dict = field(default_factory=lambda: _load_yaml(REPO / "config/skills.yaml"))

    @property
    def api_key(self) -> str:
        return os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY", "")

    @property
    def api_base(self) -> str:
        return os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")

    @property
    def model(self) -> str:
        return os.environ.get("MODEL", "muse-spark-1.3")

    @property
    def home(self) -> pathlib.Path:
        """The active agent's home. A server hosting several users sets it per turn with set_home()."""
        override = _HOME.get()
        p = override or pathlib.Path(os.environ.get("SUPERAPP_HOME", "~/.superapp/home")).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def set_home(self, path: pathlib.Path | None):
        _HOME.set(path)

    def effort(self, role: str = "root_agent") -> str:
        return self.home_yaml.get("llm", {}).get("reasoning", {}).get(role, {}).get("effort", "high")

    @property
    def resources(self) -> dict:
        return self.home_yaml.get("resources", {})

    @property
    def conversation(self) -> dict:
        return self.home_yaml.get("conversation", {})

    @property
    def memory(self) -> dict:
        return self.home_yaml.get("memory", {})

    @property
    def skills_dir(self) -> pathlib.Path:
        return REPO / "skills"

    @property
    def blocks_dir(self) -> pathlib.Path:
        return REPO / "superapp/prompts/blocks"

CONFIG = Config()
