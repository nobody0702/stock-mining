from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from stock_mining.llm.web.sources._bulk_cache import clear_bulk_cache
from stock_mining.llm.web.sources.dividends import fetch_dividend_history
from stock_mining.llm.web.sources.repurchase import fetch_repurchase_history
from stock_mining.llm.web.sources.search import search_stock_evidence
from stock_mining.llm.web.config import WebContextConfig
from stock_mining.llm.web.reporting import WebFetchReporter


def test_fetch_dividend_history_parses_rows():
    df = pd.DataFrame(
        [
            {
                "公告日期": "2026-06-22",
                "派息": 280.242,
                "进度": "实施",
            }
        ]
    )
    with patch("akshare.stock_history_dividend_detail", return_value=df):
        rows = fetch_dividend_history("600519", limit=3)
    assert len(rows) == 1
    assert rows[0].status == "实施"
    assert "280.242" in rows[0].payout


def test_fetch_repurchase_history_filters_code():
    clear_bulk_cache()
    df = pd.DataFrame(
        [
            {
                "股票代码": "600519",
                "最新公告日期": "2026-05-28",
                "实施进度": "完成实施",
                "计划回购金额区间-下限": 3e9,
                "计划回购金额区间-上限": 3e9,
                "已回购金额": 3e9,
            },
            {
                "股票代码": "000001",
                "最新公告日期": "2026-01-01",
                "实施进度": "董事会预案",
                "计划回购金额区间-下限": 1e8,
                "计划回购金额区间-上限": 2e8,
                "已回购金额": None,
            },
        ]
    )
    with patch("akshare.stock_repurchase_em", return_value=df):
        rows = fetch_repurchase_history("600519", limit=5)
    assert len(rows) == 1
    assert rows[0].status == "完成实施"
    assert "亿元" in rows[0].repurchased_amount


def test_search_stock_evidence_warns_and_continues():
    config = WebContextConfig(
        search_queries=("{name} bad", "{name} ok"),
        max_search_results_per_query=1,
    )
    reporter = WebFetchReporter()
    calls = {"n": 0}

    def _search(query: str, *, max_results: int):
        calls["n"] += 1
        if "bad" in query:
            raise ConnectionError("ddg blocked")
        from stock_mining.llm.web.models import SearchHit

        return [SearchHit(query, "t", "s", "")]

    with patch("stock_mining.llm.web.sources.search._search_web", side_effect=_search):
        hits = search_stock_evidence("600519", "贵州茅台", config, reporter=reporter)
    assert len(hits) == 1
    assert calls["n"] == 2
    assert any("DuckDuckGo" in w for w in reporter.warnings)
