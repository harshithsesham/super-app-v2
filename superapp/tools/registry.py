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


# Namespaces the model sees only as one-line stubs until it loads them with
# tool_search.load_tool_namespace (Muse's deferred tools). Everything an agent
# uses routinely stays fully loaded; these are the big, occasional surfaces.
DEFAULT_DEFERRED = {"artifact", "feed", "credentials", "chat", "wallet", "channel"}


class Registry:
    def __init__(self):
        self.schemas: dict[str, dict] = {}
        self.namespaces: dict[str, dict] = {}
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.deferred: set[str] = set(DEFAULT_DEFERRED)
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

    def is_deferred(self, name_or_ns: str) -> bool:
        return name_or_ns.split(".", 1)[0] in self.deferred

    def namespace_schemas(self, ns: str) -> list[dict]:
        """Full function schemas for one namespace, as returned to the model when it loads them."""
        return [{"name": n, "description": self.schemas[n].get("description", ""), "parameters": self.schemas[n].get("parameters")}
                for n in self.namespaces.get(ns, {}).get("functions", [])]

    def openai_tools(self, exclude_ns: set[str] | None = None, only_tools: set[str] | None = None,
                     loaded_ns: set[str] | None = None) -> list[dict]:
        """The request's tool list: every non-deferred namespace, plus deferred ones this agent has loaded."""
        out = []
        for name, fn in self.schemas.items():
            ns = name.split(".", 1)[0]
            if only_tools is not None:
                if name not in only_tools:
                    continue
            elif exclude_ns and ns in exclude_ns:
                continue
            elif ns in self.deferred and ns not in (loaded_ns or set()):
                continue
            params = fn.get("parameters") or {"type": "object", "properties": {}}
            out.append({"type": "function", "function": {
                "name": wire(name),
                "description": (fn.get("description") or "")[:1024],
                "parameters": params}})
        return out

    def runtime_section(self, exclude_ns: set[str] | None = None, only_tools: set[str] | None = None,
                        loaded_ns: set[str] | None = None) -> str:
        """The tool index in the system prompt. Deferred namespaces list every function as a one-line stub
        marked "deferred" (the marker never changes, even after loading, as Muse's prompt says)."""
        lines = ["## Runtime", "Tools available to you, by namespace. Call them by their dotted name."]
        if only_tools is not None:
            for name in sorted(only_tools):
                if name in self.schemas:
                    lines.append(f"- `{name}`: {(self.schemas[name].get('description') or '')[:300]}")
            return "\n".join(lines)
        for ns, meta in self.namespaces.items():
            if exclude_ns and ns in exclude_ns:
                continue
            deferred = ns in self.deferred
            lines.append(f"- `{ns}`: {meta['description']}" + (" (deferred namespace: load it with `tool_search.load_tool_namespace` before first use)" if deferred else ""))
            for name in meta["functions"]:
                desc = (self.schemas[name].get("description") or "").split(". ")[0][:160]
                lines.append(f"  - `{name}`: {desc}" + (" (deferred)" if deferred else ""))
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
