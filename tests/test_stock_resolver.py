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
    with pytest.raises(StockResolveError, match="未找到代码"):
        resolve_stock_inputs(["999999"], market=Market.A, list_stocks_fn=_catalog)


def test_resolve_unknown_code_allowed():
    result = resolve_stock_inputs(
        ["01045"],
        market=Market.HK,
        list_stocks_fn=lambda: [],
        allow_unknown_code=True,
    )
    assert result == [ResolvedStock("01045", "01045", Market.HK)]


def test_resolve_unknown_hk_code_explains_directory_miss():
    with pytest.raises(StockResolveError, match="港股行情目录|5 位|港股通"):
        resolve_stock_inputs(["99999"], market=Market.HK, list_stocks_fn=lambda: [])


def test_resolve_unknown_name_explains_market_hint():
    with pytest.raises(StockResolveError, match="选错市场"):
        resolve_stock_inputs(["不存在的名字"], market=Market.A, list_stocks_fn=_catalog)


def test_resolve_fuzzy_unique():
    catalog = [StockInfo("600519", "贵州茅台酒股份有限公司", Market.A)]
    result = resolve_stock_inputs(["贵州茅台"], market=Market.A, list_stocks_fn=lambda: catalog)
    assert result[0].code == "600519"
