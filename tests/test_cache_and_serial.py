from __future__ import annotations

from datetime import date

import pytest

from stock_mining.data.cache import SqliteCache, deserialize_financials, serialize_financials
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, StockFinancials


def test_cache_roundtrip_and_ttl_expiry(tmp_path):
    cache = SqliteCache(tmp_path, ttl_hours=1)
    cache.set("market", "foo", {"value": 1})
    assert cache.get("market", "foo") == {"value": 1}

    stale_cache = SqliteCache(tmp_path, ttl_hours=0)
    assert stale_cache.get("market", "foo") is None
    assert stale_cache.get_allow_stale("market", "foo") == {"value": 1}


def test_cache_namespace_prefix_isolated(tmp_path):
    a = SqliteCache(tmp_path, namespace_prefix="a")
    b = SqliteCache(tmp_path, namespace_prefix="b")
    a.set("market", "k", 1)
    b.set("market", "k", 2)
    assert a.get("market", "k") == 1
    assert b.get("market", "k") == 2


def test_financials_serialize_deserialize_roundtrip():
    original = StockFinancials(
        "688001",
        market=Market.HK,
        annual=[
            AnnualMetrics(
                date(2024, 12, 31),
                net_profit_yuan=1.5e8,
                revenue_yuan=3.2e8,
                roe_pct=12.5,
            )
        ],
    )
    payload = serialize_financials(original)
    restored = deserialize_financials(payload)
    assert restored.code == "688001"
    assert restored.market == Market.HK
    assert len(restored.annual) == 1
    assert restored.annual[0].roe_pct == pytest.approx(12.5)
