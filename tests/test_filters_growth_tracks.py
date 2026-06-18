from __future__ import annotations

from datetime import date

import pytest

from stock_mining.filters.registry import build_filter
from stock_mining.models import AnnualMetrics, MarketSnapshot, ScreeningContext, StockFinancials, StockInfo
from stock_mining.markets.base import Market


def _ctx(financials: StockFinancials, market: MarketSnapshot | None = None) -> ScreeningContext:
    return ScreeningContext(
        stock=StockInfo("688001", "样本", Market.A),
        market=market,
        financials=financials,
    )


def test_profit_window_relaxed_allows_recent_loss():
    financials = StockFinancials(
        "688001",
        annual=[
            AnnualMetrics(date(2022, 12, 31), net_profit_yuan=1e8),
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=-1e7),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-2e7),
        ],
    )
    filt = build_filter({"type": "profit_window_relaxed", "years": 3, "min_profitable_years": 1})
    assert filt.evaluate(_ctx(financials)).passed


def test_drawdown_filter():
    market = MarketSnapshot(
        code="688001",
        name="样本",
        market=Market.A,
        price=10,
        low_52w=9,
        high_52w=20,
        drawdown_from_high_pct=50,
    )
    filt = build_filter({"type": "drawdown_from_high_min", "min_pct": 25})
    assert filt.evaluate(_ctx(StockFinancials("688001"), market)).passed


def test_profit_not_deteriorating_rejects_big_drop():
    financials = StockFinancials(
        "688001",
        annual=[
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=100, revenue_yuan=200),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=50, revenue_yuan=180),
        ],
    )
    filt = build_filter({"type": "profit_not_deteriorating"})
    assert not filt.evaluate(_ctx(financials)).passed
