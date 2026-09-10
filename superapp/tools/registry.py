"""Tool registry: loads namespace schemas, exposes them in OpenAI tool format,
and dispatches calls to registered Python handlers.

Wire names replace the namespace dot with a double underscore
(`muse.exec` -> `muse__exec`) because most OpenAI-compatible gateways only
accept [A-Za-z0-9_-] in function names. Prompts keep the dotted form.
"""
from __future__ import annotations
import inspect, json, pathlib
from typing import Callable, Any

SCHEMA_DIR = pathlib.Path(__file__).resolve().parent / "schemas"


def wire(name: str) -> str:
    return name.replace(".", "__")


def unwire(name: str) -> str:
    return name.replace("__", ".", 1)


class ToolError(Exception):
    pass


class Registry:
    def __init__(self):
        self.schemas: dict[str, dict] = {}
        self.namespaces: dict[str, dict] = {}
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.deferred: set[str] = set()
        self._load()

    def _load(self):
        for p in sorted(SCHEMA_DIR.glob("*.json")):
            for entry in json.loads(p.read_text(encoding="utf-8")):
                t = entry["tool"]
                ns = t["namespace"]
                self.namespaces.setdefault(ns, {"description": t.get("description", ""), "functions": []})
                for fn in t["functions"]:
                    short = fn["name"]
                    if short.startswith(ns + "."):  # captured schemas already carry the namespace
                        short = short[len(ns) + 1:]
                    name = f"{ns}.{short}"
                    self.schemas[name] = fn
                    self.namespaces[ns]["functions"].append(name)

    def register(self, name: str, fn: Callable[..., Any] | None = None):
        if fn is None:
            def deco(f):
                self.handlers[name] = f
                return f
            return deco
        self.handlers[name] = fn
        return fn

    def defer(self, *namespaces: str):
        self.deferred.update(namespaces)

    def load_namespace(self, ns: str):
        self.deferred.discard(ns)

    def openai_tools(self, exclude_ns: set[str] | None = None, only_tools: set[str] | None = None) -> list[dict]:
        out = []
        for name, fn in self.schemas.items():
            ns = name.split(".", 1)[0]
            if only_tools is not None:
                if name not in only_tools:
                    continue
            elif ns in self.deferred or (exclude_ns and ns in exclude_ns):
                continue
            params = fn.get("parameters") or {"type": "object", "properties": {}}
            out.append({"type": "function", "function": {
                "name": wire(name),
                "description": (fn.get("description") or "")[:1024],
                "parameters": params}})
        return out

    def runtime_section(self, exclude_ns: set[str] | None = None, only_tools: set[str] | None = None) -> str:
        lines = ["## Runtime", "Tools available to you, by namespace. Call them by their dotted name."]
        if only_tools is not None:
            for name in sorted(only_tools):
                if name in self.schemas:
                    lines.append(f"- `{name}`: {(self.schemas[name].get('description') or '')[:300]}")
            return "\n".join(lines)
        for ns, meta in self.namespaces.items():
            if exclude_ns and ns in exclude_ns:
                continue
            tag = " (deferred: call `tool_search.load_tool_namespace` to expand)" if ns in self.deferred else ""
            lines.append(f"- `{ns}`: {meta['description']}{tag}")
            if ns not in self.deferred:
                for name in meta["functions"]:
                    desc = (self.schemas[name].get("description") or "").split(". ")[0]
                    lines.append(f"  - `{name}`: {desc}")
        return "\n".join(lines)

    def dispatch(self, wire_name: str, args: dict, ctx: dict | None = None) -> Any:
        name = unwire(wire_name)
        fn = self.handlers.get(name)
        if fn is None:
            raise ToolError(f"{name} has no backend implemented yet")
        try:
            if "_ctx" in inspect.signature(fn).parameters:
                return fn(**args, _ctx=ctx)
            return fn(**args)
        except TypeError as e:
            raise ToolError(f"{name}: bad arguments: {e}") from e


REGISTRY = Registry()
