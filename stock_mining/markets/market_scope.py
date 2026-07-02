from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from stock_mining.markets.base import Market, parse_market


class MarketScope(str, Enum):
    A = "a"
    HK = "h"
    US = "u"
    ALL = "all"


def parse_market_scope(value: str) -> MarketScope:
    key = value.strip().lower()
    if key == "hk":
        key = "h"
    try:
        return MarketScope(key)
    except ValueError as exc:
        raise ValueError(
            f"Unknown market scope {value!r}; use a, h, u, or all (hk is alias for h)"
        ) from exc


def _normalize_market_token(token: str) -> str:
    key = token.strip().lower()
    if key == "hk":
        return "h"
    return key


def parse_market_selection(value: str) -> list[Market]:
    """Parse market scope(s); supports comma-separated list and ``all``."""
    raw = value.strip()
    if not raw:
        raise ValueError("market selection must not be empty")

    if "," not in raw:
        return markets_for_scope(parse_market_scope(raw))

    selected: list[Market] = []
    seen: set[Market] = set()
    for part in raw.split(","):
        token = _normalize_market_token(part)
        if not token:
            continue
        for market in markets_for_scope(parse_market_scope(token)):
            if market not in seen:
                selected.append(market)
                seen.add(market)
    if not selected:
        raise ValueError(f"No markets in {value!r}")
    return selected


def market_in_selection(selected_markets: Sequence[Market], market: Market) -> bool:
    return market in selected_markets


def markets_for_scope(scope: MarketScope) -> list[Market]:
    if scope == MarketScope.ALL:
        return [Market.A, Market.HK]
    if scope == MarketScope.US:
        return [Market.US]
    return [Market(scope.value)]


def market_scope_supports(scope: MarketScope, market: Market) -> bool:
    if scope == MarketScope.ALL:
        return market in (Market.A, Market.HK)
    if scope == MarketScope.US:
        return market == Market.US
    return market.value == scope.value


def format_market_scope_help() -> str:
    return (
        "a=A股, h=港股通, u=美股(预留), all=A+港股; "
        "支持逗号组合如 a,h；股票代码请用 a:600519 / h:00700 避免撞码"
    )
