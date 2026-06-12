from __future__ import annotations

from typing import Any

from stock_mining.filters.base import Filter
from stock_mining.filters.financial import (
    DebtRatioMaxFilter,
    MarginOrWindowFilter,
    OperatingCashflowWindowFilter,
    RoeWindowFilter,
)
from stock_mining.filters.industry import ExcludeIndustryKeywordsFilter, NonDecliningIndustryFilter
from stock_mining.filters.market import (
    DividendYieldMinFilter,
    Near52WeekLowFilter,
    NonStFilter,
    ValuationByProfitFilter,
)

FILTER_TYPES: dict[str, type[Filter]] = {
    "non_st": NonStFilter,
    "exclude_industry_keywords": ExcludeIndustryKeywordsFilter,
    "non_declining_industry": NonDecliningIndustryFilter,
    "near_52w_low": Near52WeekLowFilter,
    "dividend_yield_min": DividendYieldMinFilter,
    "valuation_by_profit": ValuationByProfitFilter,
    "debt_ratio_max": DebtRatioMaxFilter,
    "margin_or_window": MarginOrWindowFilter,
    "operating_cashflow_window": OperatingCashflowWindowFilter,
    "roe_window": RoeWindowFilter,
}


def build_filter(spec: dict[str, Any]) -> Filter:
    filter_type = spec.get("type")
    if filter_type not in FILTER_TYPES:
        raise ValueError(f"Unknown filter type: {filter_type}")
    name = spec.get("name", filter_type)
    return FILTER_TYPES[filter_type](name=name, **{k: v for k, v in spec.items() if k not in {"name", "type"}})


def build_filters(specs: list[dict[str, Any]]) -> list[Filter]:
    return [build_filter(spec) for spec in specs]
