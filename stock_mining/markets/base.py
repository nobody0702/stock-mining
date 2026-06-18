from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Market(str, Enum):
    A = "a"
    HK = "hk"


@dataclass(frozen=True)
class StockId:
    code: str
    market: Market = Market.A

    @property
    def key(self) -> str:
        return f"{self.market.value}:{self.code}"


def normalize_stock_code(code: str, market: Market = Market.A) -> str:
    raw = code.strip().split(".")[0]
    if market == Market.HK:
        return raw.zfill(5)
    return raw.zfill(6)


def calc_drawdown_from_high_pct(price: float | None, high_52w: float | None) -> float | None:
    if price is None or high_52w is None or high_52w <= 0:
        return None
    return (1.0 - price / high_52w) * 100.0
