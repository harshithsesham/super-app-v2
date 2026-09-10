"""Read-only web tools for the main agent: search, open a page as numbered
text, and resolve a citation back to its URL. Keyless: search goes through
DuckDuckGo's HTML endpoint. Pages are fetched without JavaScript; anything
that needs a real browser is a browser task.
"""
from __future__ import annotations
import html as html_mod, re, urllib.parse
import httpx
from ..tools.registry import REGISTRY, ToolError
from ..connectors.gmail import html_to_text

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MAX_LINES = 400


def _cites(ctx: dict | None) -> dict:
    agent = ctx["agent"] if ctx else None
    if agent is None:
        return {}
    if not hasattr(agent, "citations"):
        agent.citations = {}  # type: ignore[attr-defined]
    return agent.citations  # type: ignore[attr-defined]


@REGISTRY.register("browser.search")
def search(query: str, max_results: int = 8, _ctx: dict | None = None):
    r = httpx.get("https://html.duckduckgo.com/html/", params={"q": query}, headers={"User-Agent": UA}, timeout=20,
                  follow_redirects=True)
    if r.status_code != 200:
        raise ToolError(f"search failed with HTTP {r.status_code}")
    out = []
    for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a class="result__snippet"[^>]*>(.*?)</a>)?', r.text, re.S):
        href, title, snippet = m.group(1), m.group(2), m.group(3) or ""
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg", [href])[0])
        title = html_mod.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        snippet = html_mod.unescape(re.sub(r"<[^>]+>", "", snippet)).strip()
        if not title or href.startswith("https://duckduckgo.com"):
            continue
        out.append({"title": title, "url": href, "snippet": snippet[:300]})
        if len(out) >= max_results:
            break
    cites = _cites(_ctx)
    for i, item in enumerate(out, 1):
        item["citation"] = f"search-{len(cites) + i}"
        cites[item["citation"]] = item["url"]
    return {"query": query, "results": out}


@REGISTRY.register("browser.open")
def open_page(url: str, _ctx: dict | None = None):
    if not re.match(r"https?://", url):
        url = "https://" + url
    try:
        r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US"}, timeout=25, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ToolError(f"could not fetch {url}: {e}")
    ctype = r.headers.get("content-type", "")
    if "html" in ctype:
        text = html_to_text(r.text)
    else:
        text = r.text[:60000]
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    truncated = len(lines) > MAX_LINES
    lines = lines[:MAX_LINES]
    numbered = "\n".join(f"L{i}: {ln[:400]}" for i, ln in enumerate(lines, 1))
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I) if "html" in ctype else None
    if m:
        title = html_mod.unescape(re.sub(r"\s+", " ", m.group(1))).strip()[:200]
    _cites(_ctx)[f"page:{str(r.url)}"] = str(r.url)
    return {"url": str(r.url), "status": r.status_code, "title": title, "lines": len(lines), "truncated": truncated,
            "text": numbered, "cite_as": "L{start}-L{end} of this page"}


@REGISTRY.register("browser.lookup_citation_url")
def lookup_citation_url(citation: str, _ctx: dict | None = None):
    cites = _cites(_ctx)
    url = cites.get(citation)
    if not url:
        raise ToolError(f"unknown citation {citation!r}; cite search results by their `citation` field")
    return {"citation": citation, "url": url}
