from __future__ import annotations

from abc import ABC, abstractmethod

from stock_mining.models import MarketSnapshot, StockFinancials, StockInfo


class MarketDataProvider(ABC):
    @abstractmethod
    def list_stocks(self) -> list[StockInfo]:
        ...

    @abstractmethod
    def fetch_dividend_map(self) -> dict[str, float]:
        ...

    @abstractmethod
    def fetch_market_snapshots(self) -> dict[str, MarketSnapshot]:
        ...

    @abstractmethod
    def fetch_stock_snapshot(self, code: str, name: str) -> MarketSnapshot:
        ...

    @abstractmethod
    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        """Map industry name -> total return percent over lookback."""

    @abstractmethod
    def fetch_financials(self, code: str) -> StockFinancials:
        ...
