"""Edge cases and YAML rule compliance tests."""

from datetime import date

import pytest

from stock_mining.config import load_pipeline_config
from stock_mining.filters.financial import (
    MarginOrWindowFilter,
    OperatingCashflowWindowFilter,
)
from stock_mining.filters.market import ValuationByProfitFilter
from stock_mining.filters.registry import build_filters
from stock_mining.models import (
    AnnualMetrics,
    MarketSnapshot,
    ScreeningContext,
    StockFinancials,
    StockInfo,
)
from stock_mining.utils import annual_window


def test_annual_window_requires_full_years_for_new_listing():
    """上市不足3年的公司：只有2期年报，应判定为不足3年。"""
    financials = StockFinancials(
        "301001",
        [
            AnnualMetrics(date(2023, 12, 31), gross_margin_pct=50, net_margin_pct=25),
            AnnualMetrics(date(2024, 12, 31), gross_margin_pct=50, net_margin_pct=25),
        ],
    )
    window = annual_window(financials.annual, 3)
    assert len(window) == 2

    margin = MarginOrWindowFilter(years=3)
    ocf = OperatingCashflowWindowFilter(years=3)
    ctx = ScreeningContext(stock=StockInfo("301001", "新股"), financials=financials)
    assert not margin.evaluate(ctx).passed
    assert "年报不足 3 年" in margin.evaluate(ctx).reason
    assert not ocf.evaluate(ctx).passed


def test_margin_missing_one_year_data_fails():
    financials = StockFinancials(
        "000001",
        [
            AnnualMetrics(date(2022, 12, 31), gross_margin_pct=50, net_margin_pct=25),
            AnnualMetrics(date(2023, 12, 31), gross_margin_pct=None, net_margin_pct=None),
            AnnualMetrics(date(2024, 12, 31), gross_margin_pct=50, net_margin_pct=25),
        ],
    )
    ctx = ScreeningContext(stock=StockInfo("000001", "测试"), financials=financials)
    result = MarginOrWindowFilter(years=3).evaluate(ctx)
    assert not result.passed


def test_valuation_rejects_invalid_pe_for_large_profit():
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", pe=-5, pb=1.0, ps=2.0),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8)],
        ),
    )
    result = ValuationByProfitFilter().evaluate(ctx)
    assert not result.passed
    assert "有效市盈率" in result.reason


def test_valuation_rejects_non_positive_pb_ps_for_small_profit():
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", pe=30, pb=-1, ps=0),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=5e7)],
        ),
    )
    assert not ValuationByProfitFilter().evaluate(ctx).passed


def test_yaml_builds_all_configured_filters():
    config = load_pipeline_config("config/daily_screen.yaml")
    filters = build_filters(config.filters)
    assert len(filters) == len(config.filters)
    names = {f.name for f in filters}
    assert names == {
        "non_st",
        "roe",
        "near_52w_low",
        "dividend_yield",
        "valuation",
        "debt_ratio",
        "margin_quality",
        "operating_cashflow",
    }


def test_yaml_thresholds_match_filter_objects():
    config = load_pipeline_config("config/daily_screen.yaml")
    filters = {f.name: f for f in build_filters(config.filters)}
    assert filters["dividend_yield"].threshold_pct == 2.0
    assert filters["roe"].min_pct == 8
    assert filters["roe"].years == 3
    assert filters["near_52w_low"].max_price_to_low_ratio == 1.05
    assert filters["margin_quality"].years == 3
    assert filters["margin_quality"].gross_margin_min_pct == 40
    assert filters["operating_cashflow"].years == 3
    assert filters["valuation"].pe_max == 20
    assert filters["debt_ratio"].threshold_pct == 40
