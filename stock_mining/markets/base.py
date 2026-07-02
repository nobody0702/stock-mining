from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stock_mining.markets.tags import normalize_bare_code, parse_market_tag


class Market(str, Enum):
    A = "a"
    HK = "h"
    US = "u"


def parse_market(value: str) -> Market:
    return Market(parse_market_tag(value))


@dataclass(frozen=True)
class StockId:
    code: str
    market: Market = Market.A

    @property
    def key(self) -> str:
        from stock_mining.markets.stock_key import build_stock_key

        return build_stock_key(self.market, self.code)


def normalize_stock_code(code: str, market: Market = Market.A) -> str:
    return normalize_bare_code(market.value, code)


def calc_drawdown_from_high_pct(price: float | None, high_52w: float | None) -> float | None:
    if price is None or high_52w is None or high_52w <= 0:
        return None
    return (1.0 - price / high_52w) * 100.0
