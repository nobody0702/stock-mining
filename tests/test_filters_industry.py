from stock_mining.filters.industry import ExcludeIndustryKeywordsFilter, NonDecliningIndustryFilter
from stock_mining.models import MarketSnapshot, ScreeningContext, StockInfo


def test_exclude_industry_keywords():
    f = ExcludeIndustryKeywordsFilter(keywords=["银行", "白酒"])
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", industry="国有大型银行"),
    )
    assert not f.evaluate(ctx).passed


def test_non_declining_industry():
    f = NonDecliningIndustryFilter(min_total_return_pct=-15, skip_if_unavailable=False)
    ok = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", industry="软件开发"),
        industry_return_3y_pct=-5,
    )
    bad = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", industry="传统零售"),
        industry_return_3y_pct=-30,
    )
    assert f.evaluate(ok).passed
    assert not f.evaluate(bad).passed


def test_non_declining_industry_skip_unavailable():
    f = NonDecliningIndustryFilter(min_total_return_pct=-15, skip_if_unavailable=True)
    ctx = ScreeningContext(
        stock=StockInfo("000001", "测试"),
        market=MarketSnapshot("000001", "测试", industry="软件开发"),
        industry_return_3y_pct=None,
    )
    assert f.evaluate(ctx).passed
