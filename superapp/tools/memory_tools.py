"""memory_search / memory_get / memory_explain backed by the home memory tree.

Search uses the hybrid vector retriever when its stack is available and
falls back to keyword matching otherwise, reporting which backend answered.
"""
from __future__ import annotations
from .registry import REGISTRY
from ..memory.files import HomeMemory
from ..memory import retrieval


def _mem() -> HomeMemory:
    return HomeMemory()


@REGISTRY.register("muse.memory_search")
def memory_search(queries: list[str], maxResults: int = 8, minScore: float = 0.0):
    r = retrieval.get_retriever()
    if r is not None:
        try:
            r.reindex()
            return {"results": r.search(queries, maxResults, minScore), "backend": "hybrid"}
        except Exception as e:  # noqa: BLE001
            reason = f"{type(e).__name__}: {e}"
    else:
        reason = retrieval.unavailable_reason()
    hits = [h for h in _mem().keyword_search(queries, maxResults) if h["score"] >= minScore]
    return {"results": hits, "backend": "keyword", "note": f"vector index unavailable: {reason}"}


@REGISTRY.register("muse.memory_get")
def memory_get(path: str, **kw):
    return _mem().get(path, kw.get("from", 1), kw.get("lines", 40))


@REGISTRY.register("muse.memory_explain")
def memory_explain(ref: str):
    # The claims store is not built yet; explain from the indexed line only, as Muse does for file-only memories.
    if "#L" in ref:
        path, line = ref.split("#L", 1)
        got = _mem().get(path, int(line), 1)
        return {"ref": ref, "claim": (got.get("lines") or [""])[0],
                "provenance": "No verified claim stands behind this memory; it was indexed from the file line "
                              "without a claim record.",
                "replaced": [], "replaced_by": [], "confidence": None}
    return {"ref": ref, "error": "only citations of the form <path>#L<n> are supported until the claims store exists"}
