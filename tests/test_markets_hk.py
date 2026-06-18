from __future__ import annotations

from stock_mining.markets.base import Market, normalize_stock_code


def test_normalize_hk_code():
    assert normalize_stock_code("700", Market.HK) == "00700"
    assert normalize_stock_code("00700", Market.HK) == "00700"


def test_normalize_a_code():
    assert normalize_stock_code("1", Market.A) == "000001"
