"""Hybrid memory retrieval, tuned exactly like Muse's home.yaml:

  embedding  Qdrant/all-MiniLM-L6-v2-onnx (384-d, cosine)      dense_weight  0.7
  sparse     BM25                                                sparse_weight 0.3
  reranker   jinaai/jina-reranker-v1-turbo-en over top 20
  priors     salience 0.15, recency 0.1 with a 90-day half-life

Index unit: one non-empty line of MEMORY.md or any ~/memory/**/*.md file
(excluding memory/index). Each hit cites `path#Lnn` so memory_get can pull
the exact lines. Qdrant runs embedded on disk under ~/memory/index unless
QDRANT_URL points at a server, so no service is required for a single user.
"""
from __future__ import annotations
import hashlib, math, os, pathlib, re, time, uuid
from datetime import datetime
from ..config import CONFIG

COLLECTION = "memory"
DENSE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # fastembed's name for Qdrant/all-MiniLM-L6-v2-onnx
SPARSE_MODEL = "Qdrant/bm25"
RERANK_MODEL = "jinaai/jina-reranker-v1-turbo-en"
_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _point_id(path: str, line: int, text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path}#L{line}:{hashlib.sha1(text.encode()).hexdigest()}"))


class Retriever:
    def __init__(self, home: pathlib.Path | None = None):
        from qdrant_client import QdrantClient, models
        from fastembed import TextEmbedding, SparseTextEmbedding
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.models = models
        self.home = home or CONFIG.home
        mem = CONFIG.memory
        self.dense_w = float(mem.get("retrieval", {}).get("dense_weight", 0.7))
        self.sparse_w = float(mem.get("retrieval", {}).get("sparse_weight", 0.3))
        self.rerank_k = int(mem.get("retrieval", {}).get("rerank_top_k", 20))
        self.salience_prior = float(mem.get("retrieval", {}).get("salience_prior", 0.15))
        self.recency_prior = float(mem.get("retrieval", {}).get("recency_prior", 0.1))
        self.half_life = float(mem.get("retrieval", {}).get("recency_half_life_days", 90.0))
        url = os.environ.get("QDRANT_URL")
        self.client = QdrantClient(url=url) if url else QdrantClient(path=str(self.home / "memory/index/qdrant"))
        self.dense = TextEmbedding(DENSE_MODEL)
        self.sparse = SparseTextEmbedding(SPARSE_MODEL)
        self.reranker = TextCrossEncoder(RERANK_MODEL)
        self._ensure_collection()

    def _ensure_collection(self):
        m = self.models
        if not self.client.collection_exists(COLLECTION):
            self.client.create_collection(
                COLLECTION,
                vectors_config={"dense": m.VectorParams(size=384, distance=m.Distance.COSINE)},
                sparse_vectors_config={"bm25": m.SparseVectorParams(modifier=m.Modifier.IDF)})

    # ---------------------------------------------------------------- index --
    def _files(self):
        yield self.home / "MEMORY.md"
        root = self.home / "memory"
        if root.exists():
            for p in sorted(root.rglob("*.md")):
                if "index" not in p.relative_to(root).parts:
                    yield p

    def _units(self):
        for p in self._files():
            if not p.exists():
                continue
            rel = p.relative_to(self.home).as_posix()
            mtime = p.stat().st_mtime
            m = _DATE_IN_NAME.search(p.name)
            ts = datetime.fromisoformat(m.group(1)).timestamp() if m else mtime
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                text = line.strip()
                if len(text) < 8 or text.startswith("#"):
                    continue
                yield {"path": rel, "line": i, "text": text, "ts": ts, "salience": 0.5}

    def reindex(self) -> dict:
        m = self.models
        units = list(self._units())
        wanted = {_point_id(u["path"], u["line"], u["text"]): u for u in units}
        existing: set[str] = set()
        offset = None
        while True:
            pts, offset = self.client.scroll(COLLECTION, limit=1000, offset=offset, with_payload=False, with_vectors=False)
            existing.update(str(p.id) for p in pts)
            if offset is None:
                break
        stale = [pid for pid in existing if pid not in wanted]
        if stale:
            self.client.delete(COLLECTION, points_selector=m.PointIdsList(points=stale))
        new = [(pid, u) for pid, u in wanted.items() if pid not in existing]
        if new:
            texts = [u["text"] for _, u in new]
            dense = list(self.dense.embed(texts))
            sparse = list(self.sparse.embed(texts))
            points = [m.PointStruct(id=pid, payload=u,
                                    vector={"dense": d.tolist(),
                                            "bm25": m.SparseVector(indices=s.indices.tolist(), values=s.values.tolist())})
                      for (pid, u), d, s in zip(new, dense, sparse)]
            self.client.upsert(COLLECTION, points=points)
        return {"indexed": len(wanted), "added": len(new), "removed": len(stale)}

    # --------------------------------------------------------------- search --
    def _recency(self, ts: float) -> float:
        age_days = max(0.0, (time.time() - ts) / 86400)
        return 0.5 ** (age_days / self.half_life)

    def search(self, queries: list[str], max_results: int = 8, min_score: float = 0.0) -> list[dict]:
        m = self.models
        candidates: dict[str, dict] = {}
        for q in queries[:3]:
            dvec = next(iter(self.dense.embed([q]))).tolist()
            svec = next(iter(self.sparse.embed([q])))
            dense_hits = self.client.query_points(COLLECTION, query=dvec, using="dense", limit=40, with_payload=True).points
            sparse_hits = self.client.query_points(
                COLLECTION, query=m.SparseVector(indices=svec.indices.tolist(), values=svec.values.tolist()),
                using="bm25", limit=40, with_payload=True).points
            dmax = max([h.score for h in dense_hits] or [1.0]) or 1.0
            smax = max([h.score for h in sparse_hits] or [1.0]) or 1.0
            for h in dense_hits:
                c = candidates.setdefault(str(h.id), {"payload": h.payload, "dense": 0.0, "sparse": 0.0})
                c["dense"] = max(c["dense"], h.score / dmax)
            for h in sparse_hits:
                c = candidates.setdefault(str(h.id), {"payload": h.payload, "dense": 0.0, "sparse": 0.0})
                c["sparse"] = max(c["sparse"], h.score / smax)
        if not candidates:
            return []
        for c in candidates.values():
            c["hybrid"] = self.dense_w * c["dense"] + self.sparse_w * c["sparse"]
        top = sorted(candidates.values(), key=lambda c: -c["hybrid"])[: self.rerank_k]
        docs = [c["payload"]["text"] for c in top]
        rr = list(self.reranker.rerank(queries[0], docs))
        for c, s in zip(top, rr):
            rel = 1 / (1 + math.exp(-float(s)))  # sigmoid to 0..1
            p = c["payload"]
            c["final"] = rel + self.salience_prior * float(p.get("salience", 0.5)) + self.recency_prior * self._recency(p["ts"])
        top.sort(key=lambda c: -c["final"])
        out = []
        for c in top:
            p = c["payload"]
            score = round(min(1.0, c["final"] / (1 + self.salience_prior + self.recency_prior)), 3)
            if score < min_score:
                continue
            out.append({"path": p["path"], "line": p["line"], "citation": f"{p['path']}#L{p['line']}",
                        "score": score, "text": p["text"]})
            if len(out) >= max_results:
                break
        return out


_RETRIEVER: Retriever | None = None
_FAILED: str | None = None


def get_retriever() -> Retriever | None:
    """Lazily build the retriever; returns None (and remembers why) if the stack is unavailable."""
    global _RETRIEVER, _FAILED
    if _RETRIEVER is None and _FAILED is None:
        try:
            _RETRIEVER = Retriever()
            _RETRIEVER.reindex()
        except Exception as e:  # noqa: BLE001
            _FAILED = f"{type(e).__name__}: {e}"
    return _RETRIEVER


def unavailable_reason() -> str | None:
    return _FAILED
