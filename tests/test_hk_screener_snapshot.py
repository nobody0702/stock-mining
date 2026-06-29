from __future__ import annotations

from stock_mining.markets.base import Market
from stock_mining.markets.snapshot_utils import snapshot_needs_price_enrichment
from stock_mining.models import MarketSnapshot, StockInfo
from stock_mining.pipeline.screener import DailyScreener


class _StubHkProvider:
    market = Market.HK

    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, str]] = []

    def fetch_stock_snapshot(self, code: str, name: str, **kwargs) -> MarketSnapshot:
        self.fetch_calls.append((code, name))
        return MarketSnapshot(
            code=code,
            name=name,
            market=Market.HK,
            price=100.0,
            low_52w=90.0,
            high_52w=120.0,
            pe=15.0,
            pb=2.0,
        )


def test_snapshot_needs_price_enrichment():
    stub = MarketSnapshot(code="00700", name="腾讯", market=Market.HK)
    full = MarketSnapshot(
        code="00700",
        name="腾讯",
        market=Market.HK,
        price=100.0,
        low_52w=90.0,
    )
    assert snapshot_needs_price_enrichment(None)
    assert snapshot_needs_price_enrichment(stub)
    assert not snapshot_needs_price_enrichment(full)


def test_resolve_snapshot_enriches_hk_stub():
    screener = DailyScreener.__new__(DailyScreener)
    provider = _StubHkProvider()
    stock = StockInfo(code="00700", name="腾讯控股", market=Market.HK)
    bulk = {
        "00700": MarketSnapshot(code="00700", name="腾讯控股", market=Market.HK),
    }
    resolved = screener._resolve_snapshot(provider, stock, bulk)
    assert resolved is not None
    assert resolved.price == 100.0
    assert provider.fetch_calls == [("00700", "腾讯控股")]
