from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from stock_mining.markets.base import Market, calc_drawdown_from_high_pct


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str
    market: Market = Market.A


@dataclass(frozen=True)
class MarketSnapshot:
    code: str
    name: str
    market: Market = Market.A
    industry: str | None = None
    price: float | None = None
    low_52w: float | None = None
    high_52w: float | None = None
    drawdown_from_high_pct: float | None = None
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    dividend_yield_pct: float | None = None
    market_cap_yuan: float | None = None

    def __post_init__(self) -> None:
        if self.drawdown_from_high_pct is None and self.price is not None and self.high_52w is not None:
            object.__setattr__(
                self,
                "drawdown_from_high_pct",
                calc_drawdown_from_high_pct(self.price, self.high_52w),
            )


@dataclass(frozen=True)
class AnnualMetrics:
    report_date: date
    net_profit_yuan: float | None = None
    revenue_yuan: float | None = None
    gross_margin_pct: float | None = None
    net_margin_pct: float | None = None
    operating_cashflow_per_share: float | None = None
    operating_cashflow_yuan: float | None = None
    debt_ratio_pct: float | None = None
    roe_pct: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StockFinancials:
    code: str
    annual: list[AnnualMetrics] = field(default_factory=list)
    market: Market = Market.A


@dataclass
class ScreeningContext:
    stock: StockInfo
    market: MarketSnapshot | None = None
    financials: StockFinancials | None = None
    industry_return_3y_pct: float | None = None
    matched_track: str | None = None


@dataclass(frozen=True)
class ScreenHit:
    code: str
    name: str
    market: Market = Market.A


@dataclass
class CandidateHit:
    code: str
    name: str
    market: Market
    track: str
    score: float
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def stock_key(self) -> str:
        return f"{self.market.value}:{self.code}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "market": self.market.value,
            "track": self.track,
            "score": round(self.score, 2),
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateHit:
        return cls(
            code=str(payload["code"]),
            name=str(payload["name"]),
            market=Market(str(payload.get("market", "a"))),
            track=str(payload["track"]),
            score=float(payload["score"]),
            metrics=dict(payload.get("metrics", {})),
        )
