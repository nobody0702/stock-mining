"""Modular web context enrichment for LLM stock analysis."""

from stock_mining.llm.web.builder import build_web_context
from stock_mining.llm.web.config import WebContextConfig
from stock_mining.llm.web.models import NoticeItem, SearchHit
from stock_mining.llm.web.sources.notices import fetch_stock_notices
from stock_mining.llm.web.sources.search import search_stock_evidence

__all__ = [
    "NoticeItem",
    "SearchHit",
    "WebContextConfig",
    "build_web_context",
    "fetch_stock_notices",
    "search_stock_evidence",
]
