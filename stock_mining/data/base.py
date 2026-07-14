from __future__ import annotations

from abc import ABC, abstractmethod

from stock_mining.markets.base import Market
from stock_mining.models import MarketSnapshot, StockFinancials, StockInfo


class MarketDataProvider(ABC):
    @property
    def market(self) -> Market:
        return Market.A

    @abstractmethod
    def list_stocks(self) -> list[StockInfo]:
        ...

    @abstractmethod
    def fetch_dividend_map(self) -> dict[str, float]:
        ...

    @abstractmethod
    def fetch_market_snapshots(
        self,
        codes: set[str] | None = None,
    ) -> dict[str, MarketSnapshot]:
        ...

    def fetch_price_snapshots(
        self,
        codes: set[str] | None = None,
        *,
        include_52w: bool = True,
    ) -> dict[str, MarketSnapshot]:
        """Cheap bulk snapshots for layered prefiltering.

        Default falls back to ``fetch_market_snapshots``. Providers may return
        price/52w-only rows and fill valuation fields later via ``enrich_snapshots``.
        """
        del include_52w  # unused in default path
        return self.fetch_market_snapshots(codes)

    def enrich_snapshots(
        self,
        snapshots: dict[str, MarketSnapshot],
    ) -> dict[str, MarketSnapshot]:
        """Fill PE/PB/PS/dividend (and similar) on an already narrowed set."""
        return snapshots

    @abstractmethod
    def fetch_stock_snapshot(
        self,
        code: str,
        name: str,
        *,
        include_dividend: bool = True,
        fast: bool = False,
    ) -> MarketSnapshot:
        ...

    @abstractmethod
    def fetch_financials(self, code: str, *, fast: bool = False) -> StockFinancials:
        ...

    def fetch_financials_cached(
        self,
        codes: list[str] | set[str],
    ) -> dict[str, StockFinancials]:
        """Return only financials already present in a warm cache. Default: empty."""
        del codes
        return {}

    @abstractmethod
    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        """Map industry name -> total return percent over lookback."""

    def enrich_snapshot_industry(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        return snapshot
