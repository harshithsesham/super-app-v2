"""Model client for the Meta Model API (OpenAI-compatible chat completions).

Muse Spark exposes reasoning effort; we pass it through `extra_body` as
`reasoning_effort` so the SDK does not reject it on stricter versions.
"""
from __future__ import annotations
from typing import Iterator
from openai import OpenAI
from .config import CONFIG

class LLM:
    def __init__(self, model: str | None = None, api_key: str | None = None, api_base: str | None = None):
        self.model = model or CONFIG.model
        self.client = OpenAI(api_key=api_key or CONFIG.api_key or "missing", base_url=api_base or CONFIG.api_base)

    def _kwargs(self, messages, tools, effort, max_tokens, stream=False) -> dict:
        kwargs: dict = dict(model=self.model, messages=messages, max_tokens=max_tokens,
                            extra_body={"reasoning_effort": effort})
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if stream:
            kwargs["stream"] = True
        return kwargs

    def complete(self, messages: list[dict], tools: list[dict] | None = None, effort: str = "high",
                 max_tokens: int = 16000):
        return self.client.chat.completions.create(**self._kwargs(messages, tools, effort, max_tokens))

    def stream(self, messages: list[dict], tools: list[dict] | None = None, effort: str = "high",
               max_tokens: int = 16000) -> Iterator:
        return self.client.chat.completions.create(**self._kwargs(messages, tools, effort, max_tokens, stream=True))

    def quick(self, system: str, user: str, effort: str = "low", max_tokens: int = 2000) -> str:
        """One-shot helper for narration, compaction, summaries."""
        r = self.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          effort=effort, max_tokens=max_tokens)
        return r.choices[0].message.content or ""
