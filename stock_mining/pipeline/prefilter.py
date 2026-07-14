"""Cheap batch / soft prefilters that shrink universe before expensive fetches."""
from __future__ import annotations

from stock_mining.filters.base import Filter
from stock_mining.filters.market import (
    DividendYieldMinFilter,
    DrawdownFromHighMinFilter,
    Near52WeekLowFilter,
    NonStFilter,
    ValuationByProfitFilter,
)
from stock_mining.models import MarketSnapshot, ScreeningContext


PRICE_ONLY_FILTER_TYPES = (
    NonStFilter,
    Near52WeekLowFilter,
    DrawdownFromHighMinFilter,
)


def is_price_only_filter(filter_: Filter) -> bool:
    return isinstance(filter_, PRICE_ONLY_FILTER_TYPES)


def needs_52w_fields(filters: list[Filter]) -> bool:
    return any(isinstance(f, (Near52WeekLowFilter, DrawdownFromHighMinFilter)) for f in filters)


def needs_valuation_fields(filters: list[Filter]) -> bool:
    return any(
        isinstance(f, (DividendYieldMinFilter, ValuationByProfitFilter)) for f in filters
    )


def soft_passes_valuation(
    snapshot: MarketSnapshot | None,
    *,
    pe_max: float,
    pb_max: float,
    ps_max: float,
) -> bool:
    """Conservative soft check: False only when valuation cannot pass either branch.

    Missing PE/PB/PS entirely → keep (cannot soft-reject before enrichment).
    """
    if snapshot is None:
        return True
    pe, pb, ps = snapshot.pe, snapshot.pb, snapshot.ps
    if pe is None and pb is None and ps is None:
        return True

    pe_ok = pe is not None and pe > 0 and pe < pe_max
    pb_ok = pb is not None and pb > 0 and pb < pb_max
    ps_ok = ps is not None and ps > 0 and ps < ps_max
    return pe_ok or pb_ok or ps_ok


def soft_passes_dividend(
    snapshot: MarketSnapshot | None,
    threshold_pct: float,
) -> bool:
    """False only when dividend is present and fails the threshold."""
    if snapshot is None or snapshot.dividend_yield_pct is None:
        return True
    return snapshot.dividend_yield_pct > threshold_pct


def track_soft_passes_market(
    ctx: ScreeningContext,
    track_filters: list[Filter],
) -> bool:
    """Market-side soft gates that do not require financial statements.

    - Existing non-financial filters are evaluated strictly when their inputs exist.
    - ValuationByProfit uses soft PE/PB/PS OR-gates (cannot soft-fail without data).
    """
    for filter_ in track_filters:
        if filter_.requires_financials:
            if isinstance(filter_, ValuationByProfitFilter):
                if not soft_passes_valuation(
                    ctx.market,
                    pe_max=filter_.pe_max,
                    pb_max=filter_.pb_max,
                    ps_max=filter_.ps_max,
                ):
                    return False
            continue
        if isinstance(filter_, DividendYieldMinFilter):
            # Missing dividend keeps the track alive until enrichment finishes;
            # present-but-low dividend hard-fails the track early.
            if ctx.market is not None and ctx.market.dividend_yield_pct is not None:
                if not filter_.evaluate(ctx).passed:
                    return False
            continue
        if not filter_.evaluate(ctx).passed:
            return False
    return True
