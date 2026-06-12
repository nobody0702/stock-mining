from __future__ import annotations

from datetime import date

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, UniverseConfig
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.registry import build_filters
from stock_mining.models import (
    AnnualMetrics,
    MarketSnapshot,
    ScreenHit,
    StockFinancials,
    StockInfo,
)
from stock_mining.pipeline.screener import DailyScreener


class FakeProvider(MarketDataProvider):
    def __init__(self) -> None:
        self.financials = StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(
                    date(2022, 12, 31),
                    net_profit_yuan=2e8,
                    gross_margin_pct=45,
                    net_margin_pct=22,
                    operating_cashflow_per_share=1.5,
                    debt_ratio_pct=30,
                    roe_pct=12,
                ),
                AnnualMetrics(
                    date(2023, 12, 31),
                    net_profit_yuan=2.1e8,
                    gross_margin_pct=44,
                    net_margin_pct=21,
                    operating_cashflow_per_share=1.2,
                    debt_ratio_pct=32,
                    roe_pct=11,
                ),
                AnnualMetrics(
                    date(2024, 12, 31),
                    net_profit_yuan=2.2e8,
                    gross_margin_pct=43,
                    net_margin_pct=20.5,
                    operating_cashflow_per_share=1.8,
                    debt_ratio_pct=35,
                    roe_pct=10,
                ),
            ],
        )
        self.snapshot = MarketSnapshot(
            code="688001",
            name="优质样本",
            industry="专用设备",
            price=10.1,
            low_52w=10.0,
            pe=15,
            pb=1.5,
            ps=2.5,
            dividend_yield_pct=3.0,
        )

    def list_stocks(self) -> list[StockInfo]:
        return [StockInfo("688001", "优质样本")]

    def fetch_market_snapshots(self) -> dict[str, MarketSnapshot]:
        return {"688001": self.snapshot}

    def fetch_dividend_map(self) -> dict[str, float]:
        return {"688001": 3.0}

    def fetch_stock_snapshot(self, code: str, name: str) -> MarketSnapshot:
        return self.snapshot

    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        return {"专用设备": 5.0}

    def fetch_financials(self, code: str) -> StockFinancials:
        return self.financials


def test_pipeline_end_to_end():
    config = PipelineConfig(
        data_source="fake",
        universe=UniverseConfig(codes=["688001"]),
        filters=[
            {"name": "non_st", "type": "non_st"},
            {"name": "roe", "type": "roe_window", "years": 3, "min_pct": 8},
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
            {"name": "dividend_yield", "type": "dividend_yield_min", "threshold_pct": 2.0},
            {
                "name": "valuation",
                "type": "valuation_by_profit",
                "profit_threshold_yuan": 100000000,
                "pe_max": 20,
                "pb_max": 2,
                "ps_max": 3,
            },
            {"name": "debt_ratio", "type": "debt_ratio_max", "threshold_pct": 40},
            {
                "name": "margin_quality",
                "type": "margin_or_window",
                "years": 3,
                "gross_margin_min_pct": 40,
                "net_margin_min_pct": 20,
            },
            {"name": "operating_cashflow", "type": "operating_cashflow_window", "years": 3},
        ],
        fetch=FetchConfig(financial_workers=1, use_cache=False),
        output=OutputConfig(directory="data/results", filename="test_screen.csv"),
    )
    provider = FakeProvider()
    screener = DailyScreener(config, provider, build_filters(config.filters))
    hits = screener.run()
    assert hits == [ScreenHit(code="688001", name="优质样本")]
