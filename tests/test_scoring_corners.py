from __future__ import annotations

from datetime import date

import pytest

from stock_mining.config import ScoringConfig
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, ScreeningContext, StockFinancials, StockInfo
from stock_mining.scoring.engine import compute_score, extract_metrics


def _ctx(
    *,
    pe: float | None = 10.0,
    pb: float | None = 1.5,
    ps: float | None = 2.0,
    dividend: float | None = 3.0,
    profit: float | None = 2e8,
    annual: list[AnnualMetrics] | None = None,
) -> ScreeningContext:
    if annual is None:
        annual = [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=profit, revenue_yuan=5e8)]
    return ScreeningContext(
        stock=StockInfo("600000", "样本", Market.A),
        market=MarketSnapshot(
            "600000",
            "样本",
            market=Market.A,
            pe=pe,
            pb=pb,
            ps=ps,
            dividend_yield_pct=dividend,
            price=10.0,
            low_52w=10.0,
            high_52w=20.0,
        ),
        financials=StockFinancials("600000", annual=annual),
    )


def test_scoring_zero_weights_returns_zero_total():
    ctx = _ctx()
    score, parts = compute_score(ctx, ScoringConfig(weights={"cheap": 0.0, "stability": 0.0}))
    assert score == 0.0
    assert "cheap" in parts


def test_scoring_missing_market_yields_zero_cheap():
    ctx = ScreeningContext(
        stock=StockInfo("600000", "样本", Market.A),
        market=None,
        financials=StockFinancials("600000", annual=[]),
    )
    score, parts = compute_score(ctx, ScoringConfig())
    assert parts["cheap"] == 0.0
    # 无足够年报时 stability 有默认兜底分 0.3，与 market 无关
    assert parts["stability"] == 0.3
    assert score == pytest.approx(15.0)


def test_scoring_profit_exactly_zero_uses_loss_making_cheap_path():
    ctx = _ctx(profit=0.0, pb=1.0, ps=2.0, dividend=4.0, pe=8.0)
    _, parts = compute_score(ctx, ScoringConfig())
    cheap_only_pb = _ctx(profit=-1e8, pb=1.0, ps=2.0, dividend=None, pe=None)
    _, loss_parts = compute_score(cheap_only_pb, ScoringConfig())
    assert parts["cheap"] == pytest.approx(loss_parts["cheap"])


def test_scoring_profitable_missing_dividend_falls_back_to_valuation_only():
    high_pe = _ctx(dividend=None, pe=28.0, pb=4.5, ps=9.0)
    low_pe = _ctx(dividend=None, pe=5.0, pb=1.0, ps=2.0)
    _, high_parts = compute_score(high_pe, ScoringConfig())
    _, low_parts = compute_score(low_pe, ScoringConfig())
    assert low_parts["cheap"] > high_parts["cheap"]


def test_scoring_profitable_negative_pe_treated_as_cheap_on_pe_axis():
    ctx = _ctx(pe=-5.0, pb=1.0, ps=2.0, dividend=2.0)
    _, parts = compute_score(ctx, ScoringConfig())
    assert parts["cheap"] > 0.5


def test_scoring_loss_making_missing_pb_ps_scores_zero_cheap():
    ctx = ScreeningContext(
        stock=StockInfo("600000", "样本", Market.A),
        market=MarketSnapshot("600000", "样本", pb=None, ps=None),
        financials=StockFinancials(
            "600000",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-1e8)],
        ),
    )
    _, parts = compute_score(ctx, ScoringConfig())
    assert parts["cheap"] == 0.0


def test_scoring_stability_single_year_defaults_to_baseline():
    ctx = _ctx(
        annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=1e8, revenue_yuan=3e8)],
    )
    _, parts = compute_score(ctx, ScoringConfig())
    assert parts["stability"] == pytest.approx(0.3)


def test_scoring_stability_flat_revenue_beats_declining():
    flat = _ctx(
        annual=[
            AnnualMetrics(date(2022, 12, 31), net_profit_yuan=1e8, revenue_yuan=5e8),
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=1.01e8, revenue_yuan=5.05e8),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=1.02e8, revenue_yuan=5.1e8),
        ],
    )
    decline = _ctx(
        annual=[
            AnnualMetrics(date(2022, 12, 31), net_profit_yuan=2e8, revenue_yuan=8e8),
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=1.2e8, revenue_yuan=6e8),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=5e7, revenue_yuan=4e8),
        ],
    )
    _, flat_parts = compute_score(flat, ScoringConfig())
    _, decline_parts = compute_score(decline, ScoringConfig())
    assert flat_parts["stability"] > decline_parts["stability"]


def test_scoring_stability_loss_making_improving_beats_worsening():
    improving = _ctx(
        profit=-2e8,
        annual=[
            AnnualMetrics(date(2022, 12, 31), net_profit_yuan=-3e8, revenue_yuan=2e8),
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=-2e8, revenue_yuan=2.2e8),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-1e8, revenue_yuan=2.5e8),
        ],
    )
    worsening = _ctx(
        profit=-3e8,
        annual=[
            AnnualMetrics(date(2022, 12, 31), net_profit_yuan=-1e8, revenue_yuan=2.5e8),
            AnnualMetrics(date(2023, 12, 31), net_profit_yuan=-2e8, revenue_yuan=2.2e8),
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=-3e8, revenue_yuan=2e8),
        ],
    )
    _, improve_parts = compute_score(improving, ScoringConfig())
    _, worse_parts = compute_score(worsening, ScoringConfig())
    assert improve_parts["stability"] > worse_parts["stability"]


def test_extract_metrics_marks_profitable_flag():
    ctx = _ctx(profit=1.0)
    score, parts = compute_score(ctx, ScoringConfig())
    metrics = extract_metrics(ctx, score, parts)
    assert metrics["profitable"] is True
    assert "score_cheap" in metrics
    assert metrics["price_to_low_ratio"] == pytest.approx(1.0)


def test_extract_metrics_includes_market_cap_from_snapshot():
    ctx = ScreeningContext(
        stock=StockInfo("600000", "样本", Market.A),
        market=MarketSnapshot(
            "600000",
            "样本",
            market=Market.A,
            pe=10.0,
            pb=1.5,
            ps=2.0,
            dividend_yield_pct=3.0,
            price=10.0,
            low_52w=10.0,
            high_52w=20.0,
            market_cap_yuan=9.46e9,
        ),
        financials=StockFinancials(
            "600000",
            annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8, revenue_yuan=5e8)],
        ),
    )
    score, parts = compute_score(ctx, ScoringConfig())
    metrics = extract_metrics(ctx, score, parts)
    assert metrics["market_cap_yuan"] == pytest.approx(9.46e9)


def test_extract_metrics_includes_interim_when_newer_than_annual():
    ctx = ScreeningContext(
        stock=StockInfo("600000", "样本", Market.A),
        market=MarketSnapshot("600000", "样本", market=Market.A, price=10.0, low_52w=10.0),
        financials=StockFinancials(
            "600000",
            annual=[
                AnnualMetrics(date(2025, 12, 31), net_profit_yuan=10.0, revenue_yuan=100.0),
                AnnualMetrics(date(2026, 6, 30), net_profit_yuan=6.0, revenue_yuan=55.0),
            ],
        ),
    )
    score, parts = compute_score(ctx, ScoringConfig())
    metrics = extract_metrics(ctx, score, parts)
    assert metrics["latest_period_label"] == "2026半年报"
    assert metrics["latest_revenue"] == pytest.approx(55.0)
    assert metrics["latest_annual_revenue"] == pytest.approx(100.0)
    assert metrics["has_newer_interim_than_annual"] is True
    assert len(metrics["current_year_interim_reports"]) == 1


def test_extract_metrics_infers_market_cap_from_ps_times_revenue():
    ctx = _ctx(profit=2e8, ps=10.0)
    score, parts = compute_score(ctx, ScoringConfig())
    metrics = extract_metrics(ctx, score, parts)
    assert metrics["market_cap_yuan"] == pytest.approx(10.0 * 5e8)
