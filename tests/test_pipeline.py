from __future__ import annotations

from datetime import date

import pytest

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, ScoringConfig, StateConfig, TrackConfig, UniverseConfig
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market, calc_drawdown_from_high_pct
from stock_mining.models import (
    AnnualMetrics,
    CandidateHit,
    MarketSnapshot,
    StockFinancials,
    StockInfo,
)
from stock_mining.pipeline.screener import DailyScreener


class FakeProvider(MarketDataProvider):
    market = Market.A

    def __init__(self) -> None:
        self.financials = StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(
                    date(2022, 12, 31),
                    net_profit_yuan=2e8,
                    revenue_yuan=5e8,
                    gross_margin_pct=45,
                    net_margin_pct=22,
                    operating_cashflow_per_share=1.5,
                    operating_cashflow_yuan=1.5e8,
                    debt_ratio_pct=30,
                    roe_pct=12,
                ),
                AnnualMetrics(
                    date(2023, 12, 31),
                    net_profit_yuan=2.1e8,
                    revenue_yuan=5.5e8,
                    gross_margin_pct=44,
                    net_margin_pct=21,
                    operating_cashflow_per_share=1.2,
                    operating_cashflow_yuan=1.4e8,
                    debt_ratio_pct=32,
                    roe_pct=11,
                ),
                AnnualMetrics(
                    date(2024, 12, 31),
                    net_profit_yuan=2.2e8,
                    revenue_yuan=6e8,
                    gross_margin_pct=43,
                    net_margin_pct=20.5,
                    operating_cashflow_per_share=1.8,
                    operating_cashflow_yuan=1.6e8,
                    debt_ratio_pct=35,
                    roe_pct=10,
                ),
            ],
        )
        self.snapshot = MarketSnapshot(
            code="688001",
            name="优质样本",
            market=Market.A,
            industry="专用设备",
            price=10.1,
            low_52w=10.0,
            high_52w=20.0,
            drawdown_from_high_pct=49.5,
            pe=15,
            pb=1.5,
            ps=2.5,
            dividend_yield_pct=3.0,
        )

    @property
    def market(self) -> Market:
        return Market.A

    def list_stocks(self) -> list[StockInfo]:
        return [StockInfo("688001", "优质样本", Market.A)]

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


def test_pipeline_end_to_end(tmp_path):
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.A],
        universe=UniverseConfig(codes=["688001"]),
        common_filters=[
            {"name": "non_st", "type": "non_st"},
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
            {"name": "drawdown", "type": "drawdown_from_high_min", "min_pct": 25},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[
                    {"name": "roe", "type": "roe_window", "years": 3, "min_pct": 8},
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
            )
        ],
        fetch=FetchConfig(financial_workers=1, use_cache=False),
        output=OutputConfig(directory=str(tmp_path), top_n=10),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=str(tmp_path / "state.sqlite3")),
        filters=[],
    )
    provider = FakeProvider()
    common_filters = build_filters(config.common_filters)
    from stock_mining.pipeline.screener import TrackEvaluator

    track_evaluators = [
        TrackEvaluator(name=track.name, filters=build_filters(track.filters))
        for track in config.tracks
    ]
    screener = DailyScreener(
        config,
        {Market.A: provider},
        common_filters,
        track_evaluators,
        state_store=None,
    )
    hits = screener.run()
    assert len(hits) == 1
    assert hits[0].code == "688001"
    assert hits[0].track == "profitable_growth"
    assert hits[0].score > 0


def test_calc_drawdown():
    assert calc_drawdown_from_high_pct(50, 100) == pytest.approx(50.0)
