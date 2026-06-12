from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    name: str
    industry: str | None = None
    price: float | None = None
    low_52w: float | None = None
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    dividend_yield_pct: float | None = None


@dataclass(frozen=True)
class AnnualMetrics:
    report_date: date
    net_profit_yuan: float | None = None
    gross_margin_pct: float | None = None
    net_margin_pct: float | None = None
    operating_cashflow_per_share: float | None = None
    debt_ratio_pct: float | None = None
    roe_pct: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StockFinancials:
    code: str
    annual: list[AnnualMetrics] = field(default_factory=list)


@dataclass
class ScreeningContext:
    stock: StockInfo
    market: MarketSnapshot | None = None
    financials: StockFinancials | None = None
    industry_return_3y_pct: float | None = None


@dataclass(frozen=True)
class ScreenHit:
    code: str
    name: str
