from __future__ import annotations

from stock_mining.filters.base import Filter
from stock_mining.models import ScreeningContext


def partition_filters(
    filters: list[Filter],
) -> tuple[list[Filter], list[Filter], list[Filter]]:
    """Split filters into (market-only, industry-returns, financial) buckets."""
    market: list[Filter] = []
    industry: list[Filter] = []
    financial: list[Filter] = []
    for filter_ in filters:
        if filter_.requires_financials:
            financial.append(filter_)
        elif filter_.requires_industry_returns:
            industry.append(filter_)
        else:
            market.append(filter_)
    return market, industry, financial


def needs_industry_name(filters: list[Filter]) -> bool:
    return any(getattr(filter_, "requires_industry_name", False) for filter_ in filters)


def needs_financials(filters: list[Filter]) -> bool:
    return any(filter_.requires_financials for filter_ in filters)


def passes_filters(ctx: ScreeningContext, filters: list[Filter]) -> bool:
    return all(filter_.evaluate(ctx).passed for filter_ in filters)


def passes_without_financials(ctx: ScreeningContext, filters: list[Filter]) -> bool:
    for filter_ in filters:
        if filter_.requires_financials:
            continue
        if not filter_.evaluate(ctx).passed:
            return False
    return True
