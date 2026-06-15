from datetime import date

import pytest

from stock_mining.filters.financial import (
    DebtRatioMaxFilter,
    MarginOrWindowFilter,
    OperatingCashflowWindowFilter,
    RoeWindowFilter,
)
from stock_mining.models import AnnualMetrics, ScreeningContext, StockFinancials, StockInfo


def _financials(**kwargs) -> StockFinancials:
    annual = [
        AnnualMetrics(date(2022, 12, 31), **kwargs),
        AnnualMetrics(date(2023, 12, 31), **kwargs),
        AnnualMetrics(date(2024, 12, 31), **kwargs),
    ]
    return StockFinancials(code="000001", annual=annual)


def test_margin_or_window_pass_by_gross():
    f = MarginOrWindowFilter(years=3, gross_margin_min_pct=40, net_margin_min_pct=20)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(gross_margin_pct=45, net_margin_pct=10),
    )
    assert f.evaluate(ctx).passed


def test_margin_or_window_pass_by_net():
    f = MarginOrWindowFilter(years=3, gross_margin_min_pct=40, net_margin_min_pct=20)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(gross_margin_pct=30, net_margin_pct=25),
    )
    assert f.evaluate(ctx).passed


def test_margin_or_window_fail():
    f = MarginOrWindowFilter(years=3, gross_margin_min_pct=40, net_margin_min_pct=20)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(gross_margin_pct=30, net_margin_pct=10),
    )
    assert not f.evaluate(ctx).passed


def test_margin_or_window_adaptive_short_history():
    f = MarginOrWindowFilter(years=3, gross_margin_min_pct=40, net_margin_min_pct=20)
    ctx = ScreeningContext(
        stock=StockInfo("301001", "新股"),
        financials=StockFinancials(
            "301001",
            [
                AnnualMetrics(date(2023, 12, 31), gross_margin_pct=50, net_margin_pct=25),
                AnnualMetrics(date(2024, 12, 31), gross_margin_pct=50, net_margin_pct=25),
            ],
        ),
    )
    assert f.evaluate(ctx).passed


def test_operating_cashflow_window():
    f = OperatingCashflowWindowFilter(years=3)
    ok = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(operating_cashflow_per_share=1.2),
    )
    bad = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=StockFinancials(
            "000001",
            [
                AnnualMetrics(date(2022, 12, 31), operating_cashflow_per_share=1),
                AnnualMetrics(date(2023, 12, 31), operating_cashflow_per_share=-0.1),
                AnnualMetrics(date(2024, 12, 31), operating_cashflow_per_share=2),
            ],
        ),
    )
    assert f.evaluate(ok).passed
    assert not f.evaluate(bad).passed


def test_operating_cashflow_window_adaptive_short_history():
    f = OperatingCashflowWindowFilter(years=3)
    ctx = ScreeningContext(
        stock=StockInfo("301001", "新股"),
        financials=StockFinancials(
            "301001",
            [
                AnnualMetrics(date(2023, 12, 31), operating_cashflow_per_share=1.0),
                AnnualMetrics(date(2024, 12, 31), operating_cashflow_per_share=2.0),
            ],
        ),
    )
    assert f.evaluate(ctx).passed


def test_debt_ratio_max_single_year():
    f = DebtRatioMaxFilter(years=3, threshold_pct=40)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), debt_ratio_pct=35)],
        ),
    )
    assert f.evaluate(ctx).passed


def test_debt_ratio_max_window_fail():
    f = DebtRatioMaxFilter(years=3, threshold_pct=40)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=StockFinancials(
            "000001",
            [
                AnnualMetrics(date(2022, 12, 31), debt_ratio_pct=30),
                AnnualMetrics(date(2023, 12, 31), debt_ratio_pct=35),
                AnnualMetrics(date(2024, 12, 31), debt_ratio_pct=42),
            ],
        ),
    )
    assert not f.evaluate(ctx).passed


def test_debt_ratio_max_window_pass():
    f = DebtRatioMaxFilter(years=3, threshold_pct=40)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(debt_ratio_pct=35),
    )
    assert f.evaluate(ctx).passed


def test_roe_window_pass():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(roe_pct=12),
    )
    assert f.evaluate(ctx).passed


def test_roe_window_fail_not_enough_high_roe():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=_financials(roe_pct=9),
    )
    assert not f.evaluate(ctx).passed


def test_roe_window_fail_not_enough_min_roe():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=StockFinancials(
            "000001",
            [
                AnnualMetrics(date(2020, 12, 31), roe_pct=12),
                AnnualMetrics(date(2021, 12, 31), roe_pct=7),
                AnnualMetrics(date(2022, 12, 31), roe_pct=7),
                AnnualMetrics(date(2023, 12, 31), roe_pct=7),
                AnnualMetrics(date(2024, 12, 31), roe_pct=7),
            ],
        ),
    )
    assert not f.evaluate(ctx).passed


def test_roe_window_pass_with_one_bad_year_in_short_window():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        financials=StockFinancials(
            "000001",
            [
                AnnualMetrics(date(2022, 12, 31), roe_pct=10),
                AnnualMetrics(date(2023, 12, 31), roe_pct=7),
                AnnualMetrics(date(2024, 12, 31), roe_pct=12),
            ],
        ),
    )
    assert f.evaluate(ctx).passed


def test_roe_window_insufficient_years_adaptive():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ctx = ScreeningContext(
        stock=StockInfo("301001", "新股"),
        financials=StockFinancials(
            "301001",
            [
                AnnualMetrics(date(2023, 12, 31), roe_pct=15),
                AnnualMetrics(date(2024, 12, 31), roe_pct=12),
            ],
        ),
    )
    assert f.evaluate(ctx).passed


def test_roe_window_single_year_requires_high_only():
    f = RoeWindowFilter(years=5, high_min_pct=10, min_pct=8)
    ok = ScreeningContext(
        stock=StockInfo("301001", "新股"),
        financials=StockFinancials(
            "301001",
            [AnnualMetrics(date(2024, 12, 31), roe_pct=11)],
        ),
    )
    bad = ScreeningContext(
        stock=StockInfo("301002", "新股"),
        financials=StockFinancials(
            "301002",
            [AnnualMetrics(date(2024, 12, 31), roe_pct=9)],
        ),
    )
    assert f.evaluate(ok).passed
    assert not f.evaluate(bad).passed
