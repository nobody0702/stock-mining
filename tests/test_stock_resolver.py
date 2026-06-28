from __future__ import annotations

import pytest

from stock_mining.llm.stock_resolver import ResolvedStock, StockResolveError, resolve_stock_inputs
from stock_mining.markets.base import Market
from stock_mining.models import StockInfo


def _catalog():
    return [
        StockInfo("600519", "贵州茅台", Market.A),
        StockInfo("000858", "五粮液", Market.A),
        StockInfo("600519", "贵州茅台", Market.A),
    ]


def test_resolve_by_code():
    result = resolve_stock_inputs(["600519"], market=Market.A, list_stocks_fn=_catalog)
    assert result == [ResolvedStock("600519", "贵州茅台", Market.A)]


def test_resolve_by_exact_name():
    result = resolve_stock_inputs(["五粮液"], market=Market.A, list_stocks_fn=_catalog)
    assert result[0].code == "000858"


def test_resolve_unknown_raises():
    with pytest.raises(StockResolveError):
        resolve_stock_inputs(["999999"], market=Market.A, list_stocks_fn=_catalog)


def test_resolve_fuzzy_unique():
    catalog = [StockInfo("600519", "贵州茅台酒股份有限公司", Market.A)]
    result = resolve_stock_inputs(["贵州茅台"], market=Market.A, list_stocks_fn=lambda: catalog)
    assert result[0].code == "600519"
