from datetime import date

import pytest

from stock_mining.models import (
    AnnualMetrics,
    MarketSnapshot,
    ScreeningContext,
    StockFinancials,
    StockInfo,
)
from stock_mining.utils import (
    annual_window,
    industry_matches_keywords,
    match_industry_return,
    parse_money_to_yuan,
    parse_percent,
)


def test_parse_percent():
    assert parse_percent("32.53%") == pytest.approx(32.53)
    assert parse_percent("False") is None


def test_parse_money_to_yuan():
    assert parse_money_to_yuan("823.20亿") == pytest.approx(823.2e8)
    assert parse_money_to_yuan("5000万") == pytest.approx(5e7)


def test_annual_window():
    rows = [
        AnnualMetrics(date(2022, 12, 31), gross_margin_pct=41),
        AnnualMetrics(date(2023, 6, 30), gross_margin_pct=30),
        AnnualMetrics(date(2023, 12, 31), gross_margin_pct=42),
        AnnualMetrics(date(2024, 12, 31), gross_margin_pct=43),
    ]
    window = annual_window(rows, 2)
    assert [item.report_date.year for item in window] == [2023, 2024]


def test_industry_keywords():
    assert industry_matches_keywords("国有大型银行", ["银行"])
    assert not industry_matches_keywords("软件开发", ["银行"])


def test_match_industry_return_partial():
    returns = {"酿酒行业": 12.5}
    assert match_industry_return("白酒酿酒", returns) == pytest.approx(12.5)
