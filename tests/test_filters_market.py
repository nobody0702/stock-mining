from stock_mining.filters.market import (
    DividendYieldMinFilter,
    Near52WeekLowFilter,
    NonStFilter,
    ValuationByProfitFilter,
)
from stock_mining.models import (
    AnnualMetrics,
    MarketSnapshot,
    ScreeningContext,
    StockFinancials,
    StockInfo,
)
from datetime import date


def test_non_st():
    f = NonStFilter()
    assert f.evaluate(ScreeningContext(StockInfo("000001", "ST测试"))).passed is False
    assert f.evaluate(ScreeningContext(StockInfo("000001", "平安银行"))).passed is True


def test_near_52w_low():
    f = Near52WeekLowFilter(max_price_to_low_ratio=1.05)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", price=10.2, low_52w=10.0),
    )
    assert f.evaluate(ctx).passed
    ctx_far = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", price=12.0, low_52w=10.0),
    )
    assert not f.evaluate(ctx_far).passed


def test_dividend_yield_min():
    f = DividendYieldMinFilter(threshold_pct=2.0)
    ok = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", dividend_yield_pct=2.5),
    )
    bad = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", dividend_yield_pct=1.5),
    )
    assert f.evaluate(ok).passed
    assert not f.evaluate(bad).passed


def test_valuation_large_profit_uses_pe():
    f = ValuationByProfitFilter(profit_threshold_yuan=1e8, pe_max=20)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", pe=15, pb=3, ps=4),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8)],
        ),
    )
    assert f.evaluate(ctx).passed


def test_valuation_large_profit_rejects_bad_pe():
    f = ValuationByProfitFilter(profit_threshold_yuan=1e8, pe_max=20)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", pe=-3, pb=1, ps=1),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8)],
        ),
    )
    assert not f.evaluate(ctx).passed


def test_valuation_small_profit_uses_pb_or_ps():
    f = ValuationByProfitFilter(profit_threshold_yuan=1e8, pb_max=2, ps_max=3)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", pe=30, pb=1.5, ps=4),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), net_profit_yuan=5e7)],
        ),
    )
    assert f.evaluate(ctx).passed
