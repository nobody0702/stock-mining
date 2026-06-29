from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, ScoringConfig, StateConfig, TrackConfig, UniverseConfig
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.pipeline.screener import DailyScreener


class NormalValueProvider(MarketDataProvider):
    market = Market.A

    def __init__(self) -> None:
        self.financials = StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(
                    date(2022, 12, 31),
                    net_profit_yuan=2e8,
                    revenue_yuan=500_000_000,
                    gross_margin_pct=35,
                    debt_ratio_pct=45,
                ),
                AnnualMetrics(
                    date(2023, 12, 31),
                    net_profit_yuan=2.1e8,
                    revenue_yuan=520_000_000,
                    gross_margin_pct=42,
                    debt_ratio_pct=46,
                ),
                AnnualMetrics(
                    date(2024, 12, 31),
                    net_profit_yuan=2.2e8,
                    revenue_yuan=540_000_000,
                    gross_margin_pct=44,
                    debt_ratio_pct=48,
                ),
            ],
        )
        self.snapshot = MarketSnapshot(
            code="688001",
            name="正常估值样本",
            market=Market.A,
            pe=22,
            pb=3.0,
            ps=2.5,
        )

    def list_stocks(self) -> list[StockInfo]:
        return [StockInfo("688001", "正常估值样本", Market.A)]

    def fetch_dividend_map(self) -> dict[str, float]:
        return {}

    def fetch_market_snapshots(self, codes=None):
        return {"688001": self.snapshot}

    def fetch_stock_snapshot(self, code, name, *, include_dividend=True, fast=False):
        return self.snapshot

    def fetch_financials(self, code, *, fast=False):
        return self.financials

    def fetch_industry_returns(self, lookback_years: int):
        return {}


def test_normal_value_strategy_track_passes(tmp_path: Path):
    track_filters = build_filters(
        [
            {"name": "gross_margin_flexible", "type": "gross_margin_flexible", "years": 3, "min_pct": 40, "min_years_meeting": 2},
            {"name": "revenue_not_severe_decline", "type": "revenue_not_severe_decline", "years": 3, "decline_pct": 10},
            {"name": "debt_ratio", "type": "debt_ratio_max", "years": 3, "threshold_pct": 50, "inclusive": True},
            {"name": "valuation", "type": "valuation_by_profit", "profit_threshold_yuan": 100_000_000, "pe_max": 30, "pb_max": 4, "ps_max": 3},
        ]
    )
    config = PipelineConfig(
        data_source="akshare",
        markets=[Market.A],
        universe=UniverseConfig(),
        common_filters=[{"name": "non_st", "type": "non_st"}],
        tracks=[TrackConfig(name="normal_valuation_stable", filters=[{}])],
        fetch=FetchConfig(),
        output=OutputConfig(directory=str(tmp_path)),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=str(tmp_path / "state.sqlite3")),
    )
    from stock_mining.pipeline.screener import TrackEvaluator

    screener = DailyScreener(
        config,
        {Market.A: NormalValueProvider()},
        build_filters([{"name": "non_st", "type": "non_st"}]),
        [TrackEvaluator(name="normal_valuation_stable", filters=track_filters)],
        state_store=None,
    )
    hits = screener.run()
    assert len(hits) == 1
    assert hits[0].track == "normal_valuation_stable"


def test_load_normal_value_config():
    root = Path(__file__).resolve().parents[1]
    from stock_mining.config import load_pipeline_config

    cfg = load_pipeline_config(root / "config" / "screen_normal_value.yaml")
    assert "normal_valuation_stable" in {track.name for track in cfg.tracks}
    assert cfg.output.candidates_json == "normal_value_candidates.json"
