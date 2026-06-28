from __future__ import annotations

from stock_mining.llm.web.config import WebContextConfig
from stock_mining.llm.web.models import SearchHit
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._safe import safe_fetch


def search_stock_evidence(
    code: str,
    name: str,
    config: WebContextConfig,
    *,
    reporter: WebFetchReporter | None = None,
) -> list[SearchHit]:
    rep = reporter or WebFetchReporter()
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for template in config.search_queries:
        query = template.format(name=name, code=code)

        def _load(q: str = query) -> list[SearchHit]:
            return _search_web(q, max_results=config.max_search_results_per_query)

        query_hits = safe_fetch(
            f"网络检索(DuckDuckGo: {query})",
            rep,
            _load,
            default=[],
        )
        for hit in query_hits:
            key = f"{hit.title}|{hit.snippet}"
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)
    return hits


def _search_web(query: str, *, max_results: int) -> list[SearchHit]:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return _search_web_ddgs_html(query, max_results=max_results)

    with DDGS() as ddgs:
        rows = ddgs.text(query, max_results=max_results)

    hits: list[SearchHit] = []
    for row in rows or []:
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("body") or row.get("snippet") or "").strip()
        url = str(row.get("href") or row.get("link") or "").strip()
        if title or snippet:
            hits.append(SearchHit(query=query, title=title, snippet=snippet, url=url))
    return hits


def _search_web_ddgs_html(query: str, *, max_results: int) -> list[SearchHit]:
    import re
    import urllib.error
    import urllib.parse
    import urllib.request

    payload = urllib.parse.urlencode({"q": query}).encode("utf-8")
    request = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=payload,
        method="POST",
        headers={"User-Agent": "Mozilla/5.0 (compatible; stock-mining/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")

    hits: list[SearchHit] = []
    blocks = re.split(r'class="result__body"', html)
    for block in blocks[1 : max_results + 1]:
        title_match = re.search(r'class="result__a".*?>(.*?)</a>', block, re.S)
        snippet_match = re.search(r'class="result__snippet".*?>(.*?)</', block, re.S)
        if not title_match:
            continue
        title = re.sub(r"<.*?>", "", title_match.group(1)).strip()
        snippet = re.sub(r"<.*?>", "", snippet_match.group(1)).strip() if snippet_match else ""
        hits.append(SearchHit(query=query, title=title, snippet=snippet, url=""))
    return hits
