from __future__ import annotations

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.filters.registry import build_filter
from stock_mining.models import ScreeningContext, StockInfo
from stock_mining.pipeline.funnel import (
    needs_financials,
    needs_industry_name,
    partition_filters,
    passes_filters,
    passes_without_financials,
)


class AlwaysPassFilter(Filter):
    name = "always_pass"

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        return FilterResult(True, "ok")


class AlwaysFailFilter(Filter):
    name = "always_fail"

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        return FilterResult(False, "no")


class NeedsFinancialFilter(Filter):
    name = "needs_financial"

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        return FilterResult(ctx.financials is not None, "need financials")


def test_partition_filters_splits_by_requirements():
    market = build_filter({"name": "non_st", "type": "non_st"})
    industry = build_filter(
        {
            "name": "non_declining_industry",
            "type": "non_declining_industry",
            "skip_if_unavailable": False,
        }
    )
    financial = build_filter({"name": "roe", "type": "roe_window", "years": 3, "min_pct": 8})
    m, i, f = partition_filters([market, industry, financial])
    assert market in m
    assert industry in i
    assert financial in f


def test_passes_without_financials_skips_financial_bucket():
    ctx = ScreeningContext(stock=StockInfo("000001", "测试"))
    filters = [AlwaysPassFilter(), NeedsFinancialFilter()]
    assert passes_without_financials(ctx, filters)
    assert not passes_filters(ctx, filters)


def test_needs_industry_name_for_keyword_filter():
    filt = build_filter(
        {"name": "exclude", "type": "exclude_industry_keywords", "keywords": ["银行"]}
    )
    assert needs_industry_name([filt])


def test_filter_group_any_partition_marks_financial_when_child_needs_it():
    group = build_filter(
        {
            "name": "group",
            "type": "filter_group_any",
            "groups": [[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 1}]],
        }
    )
    _, _, financial = partition_filters([group])
    assert group in financial
    assert needs_financials([group])
