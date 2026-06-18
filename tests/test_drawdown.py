from __future__ import annotations

from stock_mining.markets.base import Market, calc_drawdown_from_high_pct
from stock_mining.models import MarketSnapshot


def test_market_snapshot_drawdown_post_init():
    snap = MarketSnapshot(
        code="688001",
        name="样本",
        market=Market.A,
        price=50,
        high_52w=100,
    )
    assert snap.drawdown_from_high_pct == calc_drawdown_from_high_pct(50, 100)
