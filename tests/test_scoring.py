from __future__ import annotations

from datetime import date

import pytest

from stock_mining.config import ScoringConfig
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, ScreeningContext, StockFinancials, StockInfo
from stock_mining.scoring.engine import compute_score


def test_scoring_profitable_prefers_high_dividend_and_low_pe():
    high_dividend = ScreeningContext(
        stock=StockInfo("688001", "样本A", Market.A),
        market=MarketSnapshot(
            code="688001",
            name="样本A",
            market=Market.A,
            pe=10,
            pb=1.5,
            ps=2.0,
            dividend_yield_pct=4.0,
        ),
        financials=StockFinancials(
            "688001",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8, revenue_yuan=5e8)],
        ),
    )
    low_dividend = ScreeningContext(
        stock=StockInfo("688002", "样本B", Market.A),
        market=MarketSnapshot(
            code="688002",
            name="样本B",
            market=Market.A,
            pe=25,
            pb=4.0,
            ps=8.0,
            dividend_yield_pct=0.5,
        ),
        financials=StockFinancials(
            "688002",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8, revenue_yuan=5e8)],
        ),
    )

    high_score, high_parts = compute_score(high_dividend, ScoringConfig())
    low_score, low_parts = compute_score(low_dividend, ScoringConfig())

    assert high_score > low_score
    assert high_parts["cheap"] > low_parts["cheap"]


def test_scoring_loss_making_prefers_low_pb():
    cheap = ScreeningContext(
        stock=StockInfo("688003", "亏损A", Market.A),
        market=MarketSnapshot(code="688003", name="亏损A", market=Market.A, pb=1.0, ps=2.0),
        financials=StockFinancials(
            "688003",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-1e8, revenue_yuan=3e8)],
        ),
    )
    expensive = ScreeningContext(
        stock=StockInfo("688004", "亏损B", Market.A),
        market=MarketSnapshot(code="688004", name="亏损B", market=Market.A, pb=6.0, ps=10.0),
        financials=StockFinancials(
            "688004",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-1e8, revenue_yuan=3e8)],
        ),
    )

    cheap_score, cheap_parts = compute_score(cheap, ScoringConfig())
    expensive_score, expensive_parts = compute_score(expensive, ScoringConfig())

    assert cheap_score > expensive_score
    assert cheap_parts["cheap"] > expensive_parts["cheap"]


def test_scoring_stability_prefers_growth_over_decline():
    growing = ScreeningContext(
        stock=StockInfo("688005", "成长", Market.A),
        market=MarketSnapshot(code="688005", name="成长", market=Market.A, dividend_yield_pct=2.0),
        financials=StockFinancials(
            "688005",
            annual=[
                AnnualMetrics(date(2022, 12, 31), net_profit_yuan=1e8, revenue_yuan=4e8),
                AnnualMetrics(date(2023, 12, 31), net_profit_yuan=1.2e8, revenue_yuan=4.5e8),
                AnnualMetrics(date(2024, 12, 31), net_profit_yuan=1.5e8, revenue_yuan=5e8),
            ],
        ),
    )
    declining = ScreeningContext(
        stock=StockInfo("688006", "下滑", Market.A),
        market=MarketSnapshot(code="688006", name="下滑", market=Market.A, dividend_yield_pct=2.0),
        financials=StockFinancials(
            "688006",
            annual=[
                AnnualMetrics(date(2022, 12, 31), net_profit_yuan=2e8, revenue_yuan=6e8),
                AnnualMetrics(date(2023, 12, 31), net_profit_yuan=1.5e8, revenue_yuan=5e8),
                AnnualMetrics(date(2024, 12, 31), net_profit_yuan=1e8, revenue_yuan=4e8),
            ],
        ),
    )

    grow_score, grow_parts = compute_score(growing, ScoringConfig())
    decline_score, decline_parts = compute_score(declining, ScoringConfig())

    assert grow_parts["stability"] > decline_parts["stability"]
    assert grow_score != pytest.approx(decline_score)
