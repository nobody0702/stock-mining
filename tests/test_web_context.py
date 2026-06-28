from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from stock_mining.llm.web.builder import build_web_context
from stock_mining.llm.web.classifier import classify_notices
from stock_mining.llm.web.config import WebContextConfig
from stock_mining.llm.web.models import (
    DividendRecord,
    NoticeItem,
    PledgeSummary,
    RepurchaseRecord,
    SearchHit,
)
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._safe import safe_fetch


def test_build_web_context_combines_sections():
    config = WebContextConfig(
        enable_notices=True,
        enable_notice_classification=True,
        enable_dividends=True,
        enable_repurchase=True,
        enable_pledge=True,
        enable_web_search=True,
        search_queries=("{name} test",),
    )
    notices = [NoticeItem("2026-01-01", "贵州茅台2025年年度权益分派实施公告", "分配方案实施")]
    with patch(
        "stock_mining.llm.web.builder.fetch_stock_notices",
        return_value=notices,
    ), patch(
        "stock_mining.llm.web.builder.fetch_dividend_history",
        return_value=[DividendRecord("2026-06-22", "每10股派280.242元", "实施")],
    ), patch(
        "stock_mining.llm.web.builder.fetch_repurchase_history",
        return_value=[
            RepurchaseRecord("2026-05-28", "完成实施", "30亿元", "30亿元"),
        ],
    ), patch(
        "stock_mining.llm.web.builder.fetch_pledge_summary",
        return_value=PledgeSummary("0%", "未查到质押记录"),
    ), patch(
        "stock_mining.llm.web.builder.search_stock_evidence",
        return_value=[SearchHit("q", "标题", "摘要", "http://x")],
    ):
        text = build_web_context("600519", "贵州茅台", config=config)
    assert "公告摘录" in text
    assert "公告要点分类" in text
    assert "分红记录" in text
    assert "回购记录" in text
    assert "股权质押" in text
    assert "网络检索摘要" in text
    assert "标题" in text


def test_build_web_context_empty_when_no_data():
    config = WebContextConfig()
    with patch("stock_mining.llm.web.builder.fetch_stock_notices", return_value=[]), patch(
        "stock_mining.llm.web.builder.fetch_dividend_history",
        return_value=[],
    ), patch(
        "stock_mining.llm.web.builder.fetch_repurchase_history",
        return_value=[],
    ), patch(
        "stock_mining.llm.web.builder.fetch_pledge_summary",
        return_value=None,
    ), patch(
        "stock_mining.llm.web.builder.search_stock_evidence",
        return_value=[],
    ):
        assert build_web_context("600519", "贵州茅台", config=config) == ""


def test_build_web_context_continues_on_partial_failure():
    config = WebContextConfig(
        enable_notices=False,
        enable_notice_classification=False,
        enable_web_search=False,
        enable_dividends=True,
        enable_repurchase=True,
        enable_pledge=False,
    )
    warnings: list[str] = []
    repurchase_df = pd.DataFrame(
        [
            {
                "股票代码": "600519",
                "最新公告日期": "2026-05-28",
                "实施进度": "完成实施",
                "计划回购金额区间-下限": 3e9,
                "计划回购金额区间-上限": 3e9,
                "已回购金额": 3e9,
            }
        ]
    )
    from stock_mining.llm.web.sources._bulk_cache import clear_bulk_cache

    clear_bulk_cache()
    with patch(
        "akshare.stock_history_dividend_detail",
        side_effect=ConnectionError("network down"),
    ), patch("akshare.stock_repurchase_em", return_value=repurchase_df):
        text = build_web_context(
            "600519",
            "贵州茅台",
            config=config,
            on_warning=warnings.append,
        )
    assert "回购记录" in text
    assert any("分红历史" in w for w in warnings)


def test_classify_notices_tags_management_and_dividend():
    notices = [
        NoticeItem("2026-06-12", "贵州茅台关于聘任董事会秘书的公告", "高管人员任职变动"),
        NoticeItem("2026-06-22", "贵州茅台2025年年度权益分派实施公告", "分配方案实施"),
        NoticeItem("2026-04-01", "日常经营公告", "其他"),
    ]
    tagged = classify_notices(notices)
    tags = {item.tag for item in tagged}
    assert "管理层变动" in tags
    assert "回购/分红" in tags


def test_safe_fetch_returns_default_and_reports():
    reporter = WebFetchReporter()
    value = safe_fetch(
        "test-source",
        reporter,
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        default=[],
    )
    assert value == []
    assert len(reporter.warnings) == 1
    assert "test-source" in reporter.warnings[0]
    assert "RuntimeError" in reporter.warnings[0]


def test_web_context_facade_exports():
    from stock_mining.llm import web_context as facade

    assert facade.build_web_context is build_web_context
    assert facade.WebContextConfig is WebContextConfig
