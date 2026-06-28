"""Backward-compatible facade for web context enrichment."""

from stock_mining.llm.web import (
    NoticeItem,
    SearchHit,
    WebContextConfig,
    build_web_context,
    fetch_stock_notices,
    search_stock_evidence,
)

__all__ = [
    "NoticeItem",
    "SearchHit",
    "WebContextConfig",
    "build_web_context",
    "fetch_stock_notices",
    "search_stock_evidence",
]
