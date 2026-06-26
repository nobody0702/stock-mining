from __future__ import annotations

from datetime import date

import pytest

from stock_mining.config import ScoringConfig
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, ScreeningContext, StockFinancials, StockInfo
from stock_mining.scoring.engine import compute_score, extract_metrics
from stock_mining.scoring.valuation import (
    ValuationConfig,
    ValuationScenarioConfig,
    ValuationTier,
    compute_valuation_metrics,
    load_valuation_config,
    load_valuation_scenarios,
)


def test_pe_margin_when_overvalued():
    # profit=51.9M, fair_pe=15 -> intrinsic_mc=778.6M; pe=67.77 -> market_mc ~ 3.52B
    metrics = compute_valuation_metrics(
        price=48.5,
        market_cap_yuan=67.77 * 51_908_100,
        latest_net_profit_yuan=51_908_100.0,
        latest_operating_cashflow_yuan=None,
        pe=67.77,
        config=ValuationConfig(fair_pe=15.0),
    )
    assert metrics["valuation_pe_available"] is True
    assert metrics["margin_of_safety_pe_pct"] < 0
    assert metrics["intrinsic_price_pe"] == pytest.approx(48.5 * 15 / 67.77, rel=1e-3)


def test_pe_margin_when_undervalued():
    metrics = compute_valuation_metrics(
        price=10.0,
        market_cap_yuan=10.0 * 100_000_000,
        latest_net_profit_yuan=100_000_000.0,
        latest_operating_cashflow_yuan=None,
        pe=10.0,
        config=ValuationConfig(fair_pe=15.0),
    )
    assert metrics["margin_of_safety_pe_pct"] == pytest.approx(33.33, abs=0.1)
    assert metrics["intrinsic_price_pe"] == pytest.approx(15.0, rel=1e-3)


def test_dcf_uses_operating_cashflow_when_positive():
    cfg = ValuationConfig(discount_rate=0.10, terminal_growth=0.03, fair_pe=15.0)
    ocf = 80_000_000.0
    metrics = compute_valuation_metrics(
        price=20.0,
        market_cap_yuan=800_000_000.0,
        latest_net_profit_yuan=50_000_000.0,
        latest_operating_cashflow_yuan=ocf,
        pe=16.0,
        config=cfg,
    )
    assert metrics["owner_earnings_source"] == "operating_cashflow"
    assert metrics["valuation_dcf_available"] is True
    expected_intrinsic = ocf * 1.03 / (0.10 - 0.03)
    assert metrics["intrinsic_value_dcf_yuan"] == pytest.approx(expected_intrinsic, rel=1e-4)
    assert metrics["margin_of_safety_dcf_pct"] > 0


def test_dcf_unavailable_when_no_positive_earnings():
    metrics = compute_valuation_metrics(
        price=10.0,
        market_cap_yuan=1_000_000_000.0,
        latest_net_profit_yuan=-10_000_000.0,
        latest_operating_cashflow_yuan=-5_000_000.0,
        pe=-50.0,
        config=ValuationConfig(),
    )
    assert metrics["valuation_dcf_available"] is False
    assert metrics["valuation_pe_available"] is False
    assert "margin_of_safety_pct" not in metrics


def test_conservative_margin_uses_minimum_of_methods():
    metrics = compute_valuation_metrics(
        price=10.0,
        market_cap_yuan=100.0,
        latest_net_profit_yuan=10.0,
        latest_operating_cashflow_yuan=10.0,
        pe=10.0,
        config=ValuationConfig(fair_pe=20.0, discount_rate=0.10, terminal_growth=0.03),
    )
    assert metrics["margin_of_safety_pe_pct"] == pytest.approx(50.0, abs=0.1)
    assert metrics["margin_of_safety_dcf_pct"] == pytest.approx(32.06, abs=0.2)
    assert metrics["margin_of_safety_pct"] == pytest.approx(32.06, abs=0.2)


def test_multi_tier_valuation_from_project_yaml():
    metrics = compute_valuation_metrics(
        price=10.0,
        market_cap_yuan=150.0,
        latest_net_profit_yuan=10.0,
        latest_operating_cashflow_yuan=10.0,
        pe=15.0,
    )
    tiers = metrics["valuation_tiers"]
    assert len(tiers) == 4
    ids = {row["id"] for row in tiers}
    assert ids == {"deep_value", "baseline", "quality_compounder", "elite_franchise"}
    deep_value = next(row for row in tiers if row["id"] == "deep_value")
    baseline = next(row for row in tiers if row["id"] == "baseline")
    elite = next(row for row in tiers if row["id"] == "elite_franchise")
    assert deep_value["margin_of_safety_pe_pct"] < elite["margin_of_safety_pe_pct"]
    assert metrics["valuation_default_tier"] == "baseline"
    assert metrics["margin_of_safety_pe_pct"] == baseline["margin_of_safety_pe_pct"]


def test_custom_scenarios_override_yaml():
    scenarios = ValuationScenarioConfig(
        default_tier_id="test",
        tiers=(
            ValuationTier(
                id="test",
                label="测试档",
                fair_pe=12.0,
                discount_rate=0.11,
                terminal_growth=0.025,
                typical_for="单测",
            ),
        ),
    )
    metrics = compute_valuation_metrics(
        price=12.0,
        market_cap_yuan=120.0,
        latest_net_profit_yuan=10.0,
        latest_operating_cashflow_yuan=None,
        pe=12.0,
        scenarios=scenarios,
    )
    assert len(metrics["valuation_tiers"]) == 1
    assert metrics["valuation_tiers"][0]["fair_pe"] == 12.0
    assert metrics["margin_of_safety_pe_pct"] == pytest.approx(0.0, abs=0.1)


def test_extract_metrics_includes_valuation_fields():
    ctx = ScreeningContext(
        stock=StockInfo("688001", "样本", Market.A),
        market=MarketSnapshot(
            code="688001",
            name="样本",
            market=Market.A,
            price=10.0,
            pe=20.0,
            pb=2.0,
            ps=3.0,
        ),
        financials=StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(
                    date(2024, 12, 31),
                    net_profit_yuan=100_000_000.0,
                    revenue_yuan=500_000_000.0,
                    operating_cashflow_yuan=120_000_000.0,
                )
            ],
        ),
    )
    score, components = compute_score(ctx, ScoringConfig())
    metrics = extract_metrics(ctx, score, components)
    assert "margin_of_safety_pe_pct" in metrics
    assert "margin_of_safety_dcf_pct" in metrics
    assert "intrinsic_price_pe" in metrics
    assert "latest_operating_cashflow" in metrics
    assert "valuation_tiers" in metrics
    assert len(metrics["valuation_tiers"]) == 4
    assert metrics["valuation_fair_pe"] == load_valuation_config().fair_pe


def test_load_valuation_config_from_project_yaml():
    cfg = load_valuation_config()
    assert cfg.discount_rate == 0.10
    assert cfg.terminal_growth == 0.03
    assert cfg.fair_pe == 15.0


def test_load_valuation_scenarios_from_project_yaml():
    scenarios = load_valuation_scenarios()
    assert scenarios.default_tier_id == "baseline"
    assert len(scenarios.tiers) == 4
    assert scenarios.tiers[1].fair_pe == 15.0
