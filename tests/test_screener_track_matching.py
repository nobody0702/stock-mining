from __future__ import annotations

from datetime import date

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, ScoringConfig, StateConfig, TrackConfig, UniverseConfig
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.pipeline.screener import DailyScreener, TrackEvaluator


class SnapshotOnlyProvider:
    market = Market.A

    def __init__(self, snapshots: dict[str, MarketSnapshot], financials: dict[str, StockFinancials]) -> None:
        self.snapshots = snapshots
        self.financials = financials
        self.financial_calls = 0

    @property
    def market(self) -> Market:
        return Market.A

    def list_stocks(self) -> list[StockInfo]:
        return [StockInfo(code, snap.name, Market.A) for code, snap in self.snapshots.items()]

    def fetch_market_snapshots(self, codes: set[str] | None = None) -> dict[str, MarketSnapshot]:
        if codes is None:
            return dict(self.snapshots)
        return {code: self.snapshots[code] for code in codes if code in self.snapshots}

    def fetch_dividend_map(self) -> dict[str, float]:
        return {}

    def fetch_stock_snapshot(self, code: str, name: str) -> MarketSnapshot:
        return self.snapshots[code]

    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        return {}

    def enrich_snapshot_industry(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        return snapshot

    def fetch_financials(self, code: str) -> StockFinancials:
        self.financial_calls += 1
        return self.financials[code]


def _financials(code: str, roe: float) -> StockFinancials:
    return StockFinancials(
        code,
        annual=[AnnualMetrics(date(2024, 12, 31), net_profit_yuan=2e8, roe_pct=roe, revenue_yuan=5e8)],
    )


def test_screener_picks_first_matching_track_in_config_order():
    snapshots = {
        "688001": MarketSnapshot(
            "688001",
            "双轨样本",
            price=10.0,
            low_52w=10.0,
            high_52w=20.0,
            pe=12.0,
            pb=1.5,
            ps=2.0,
            dividend_yield_pct=3.0,
        ),
    }
    provider = SnapshotOnlyProvider(
        snapshots,
        {"688001": _financials("688001", roe=9.0)},
    )
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.A],
        universe=UniverseConfig(codes=["688001"]),
        common_filters=[
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8, "high_min_pct": 10}],
            ),
            TrackConfig(
                name="loss_tolerant_growth",
                filters=[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8, "high_min_pct": 8}],
            ),
        ],
        fetch=FetchConfig(use_cache=False),
        output=OutputConfig(directory="data/results"),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=":memory:"),
        filters=[],
    )
    tracks = [TrackEvaluator(name=t.name, filters=build_filters(t.filters)) for t in config.tracks]
    screener = DailyScreener(
        config,
        {Market.A: provider},
        build_filters(config.common_filters),
        tracks,
        state_store=None,
    )
    hits = screener.run()
    assert len(hits) == 1
    assert hits[0].track == "loss_tolerant_growth"
    assert provider.financial_calls == 1


def test_screener_when_both_tracks_match_picks_first():
    snapshots = {
        "688003": MarketSnapshot(
            "688003",
            "双轨全命中",
            price=10.0,
            low_52w=10.0,
            high_52w=20.0,
            pe=12.0,
            pb=1.5,
            ps=2.0,
            dividend_yield_pct=3.0,
        ),
    }
    provider = SnapshotOnlyProvider(
        snapshots,
        {"688003": _financials("688003", roe=12.0)},
    )
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.A],
        universe=UniverseConfig(codes=["688003"]),
        common_filters=[
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8, "high_min_pct": 10}],
            ),
            TrackConfig(
                name="loss_tolerant_growth",
                filters=[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8, "high_min_pct": 8}],
            ),
        ],
        fetch=FetchConfig(use_cache=False),
        output=OutputConfig(directory="data/results"),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=":memory:"),
        filters=[],
    )
    tracks = [TrackEvaluator(name=t.name, filters=build_filters(t.filters)) for t in config.tracks]
    screener = DailyScreener(
        config,
        {Market.A: provider},
        build_filters(config.common_filters),
        tracks,
        state_store=None,
    )
    hits = screener.run()
    assert len(hits) == 1
    assert hits[0].track == "profitable_growth"


def test_screener_skips_financial_fetch_when_market_filter_fails():
    snapshots = {
        "688002": MarketSnapshot("688002", "太远", price=20.0, low_52w=10.0, high_52w=30.0),
    }
    provider = SnapshotOnlyProvider(snapshots, {"688002": _financials("688002", 15.0)})
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.A],
        universe=UniverseConfig(codes=["688002"]),
        common_filters=[
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[{"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8}],
            )
        ],
        fetch=FetchConfig(use_cache=False),
        output=OutputConfig(directory="data/results"),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=":memory:"),
        filters=[],
    )
    tracks = [TrackEvaluator(name=t.name, filters=build_filters(t.filters)) for t in config.tracks]
    screener = DailyScreener(
        config,
        {Market.A: provider},
        build_filters(config.common_filters),
        tracks,
        state_store=None,
    )
    assert screener.run() == []
    assert provider.financial_calls == 0
