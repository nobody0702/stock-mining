from __future__ import annotations

from datetime import date

import pytest

from stock_mining.models import AnnualMetrics, MarketSnapshot, ScreeningContext, StockFinancials, StockInfo
from stock_mining.markets.base import Market
from stock_mining.scoring.engine import compute_score
from stock_mining.config import ScoringConfig


def test_scoring_prefers_near_low_and_high_drawdown():
    ctx = ScreeningContext(
        stock=StockInfo("688001", "样本", Market.A),
        market=MarketSnapshot(
            code="688001",
            name="样本",
            market=Market.A,
            price=10,
            low_52w=10,
            high_52w=20,
            drawdown_from_high_pct=50,
        ),
        financials=StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(date(2024, 12, 31), roe_pct=15, net_profit_yuan=1e8, revenue_yuan=2e8)
            ],
        ),
    )
    score, components = compute_score(ctx, ScoringConfig())
    assert score > 50
    assert components["near_low"] == pytest.approx(1.0)
    assert components["drawdown"] == pytest.approx(1.0)
