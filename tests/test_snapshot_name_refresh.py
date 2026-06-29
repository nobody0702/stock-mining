from __future__ import annotations

from stock_mining.data.akshare_provider import AkshareDataProvider
from stock_mining.markets.base import Market
from stock_mining.models import MarketSnapshot


def test_fetch_stock_snapshot_prefers_fresh_name_over_stale_cache(tmp_path):
    stale = {
        "code": "600007",
        "name": "中国国贸",
        "market": "a",
        "industry": None,
        "price": 18.0,
        "low_52w": 17.0,
        "high_52w": 22.0,
        "drawdown_from_high_pct": None,
        "pe": 15.0,
        "pb": 2.0,
        "ps": None,
        "dividend_yield_pct": None,
        "market_cap_yuan": None,
    }
    provider = AkshareDataProvider(
        use_cache=True,
        cache_dir=str(tmp_path),
        request_interval_sec=0,
        network_retries=1,
    )
    provider.cache.set("market", "snapshot_600007", stale)
    snapshot = provider.fetch_stock_snapshot("600007", "XD中国国", fast=True)
    assert snapshot.code == "600007"
    assert snapshot.name == "XD中国国"
    assert snapshot.market == Market.A
    assert isinstance(snapshot, MarketSnapshot)
