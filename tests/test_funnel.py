from __future__ import annotations

from datetime import date

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, ScoringConfig, StateConfig, TrackConfig, UniverseConfig
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.pipeline.screener import DailyScreener, TrackEvaluator


class CountingProvider(MarketDataProvider):
    def __init__(self, *, pass_market: bool) -> None:
        self.pass_market = pass_market
        self.financial_calls = 0
        self.industry_calls = 0
        self.snapshot = MarketSnapshot(
            code="688001",
            name="样本",
            market=Market.A,
            price=10.0,
            low_52w=10.0,
            high_52w=20.0,
            drawdown_from_high_pct=50.0,
            pe=15.0,
            pb=1.5,
            dividend_yield_pct=3.0,
        )
        self.financials = StockFinancials(
            "688001",
            annual=[
                AnnualMetrics(
                    date(2024, 12, 31),
                    net_profit_yuan=2e8,
                    revenue_yuan=6e8,
                    gross_margin_pct=43,
                    net_margin_pct=20.5,
                    operating_cashflow_per_share=1.8,
                    operating_cashflow_yuan=1.6e8,
                    debt_ratio_pct=35,
                    roe_pct=11,
                )
            ],
        )

    @property
    def market(self) -> Market:
        return Market.A

    def list_stocks(self) -> list[StockInfo]:
        return [
            StockInfo("688001", "样本", Market.A),
            StockInfo("688002", "淘汰", Market.A),
        ]

    def fetch_market_snapshots(
        self,
        codes: set[str] | None = None,
    ) -> dict[str, MarketSnapshot]:
        if self.pass_market:
            snapshots = {
                "688001": self.snapshot,
                "688002": MarketSnapshot(
                    code="688002",
                    name="淘汰",
                    market=Market.A,
                    price=20.0,
                    low_52w=10.0,
                    high_52w=25.0,
                ),
            }
        else:
            snapshots = {
                "688001": MarketSnapshot(
                    code="688001",
                    name="样本",
                    market=Market.A,
                    price=20.0,
                    low_52w=10.0,
                    high_52w=25.0,
                ),
                "688002": MarketSnapshot(
                    code="688002",
                    name="淘汰",
                    market=Market.A,
                    price=20.0,
                    low_52w=10.0,
                    high_52w=25.0,
                ),
            }
        if codes is None:
            return snapshots
        return {code: snapshots[code] for code in codes if code in snapshots}

    def fetch_dividend_map(self) -> dict[str, float]:
        return {"688001": 3.0}

    def fetch_stock_snapshot(self, code: str, name: str, *, include_dividend: bool = True, fast: bool = False) -> MarketSnapshot:
        return self.fetch_market_snapshots()[code]

    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        return {}

    def enrich_snapshot_industry(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        self.industry_calls += 1
        return snapshot

    def fetch_financials(self, code: str, *, fast: bool = False) -> StockFinancials:
        self.financial_calls += 1
        return self.financials


def _build_screener(provider: CountingProvider) -> DailyScreener:
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.A],
        universe=UniverseConfig(),
        common_filters=[
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.05},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[
                    {"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8},
                ],
            )
        ],
        fetch=FetchConfig(financial_workers=1, use_cache=False),
        output=OutputConfig(directory="data/results", top_n=10),
        scoring=ScoringConfig(),
        state=StateConfig(db_path="data/state/test.sqlite3"),
        filters=[],
    )
    common_filters = build_filters(config.common_filters)
    tracks = [
        TrackEvaluator(name=track.name, filters=build_filters(track.filters))
        for track in config.tracks
    ]
    return DailyScreener(
        config,
        {Market.A: provider},
        common_filters,
        tracks,
        state_store=None,
    )


def test_funnel_skips_financials_when_market_filter_fails():
    provider = CountingProvider(pass_market=False)
    hits = _build_screener(provider).run()
    assert hits == []
    assert provider.financial_calls == 0


def test_funnel_fetches_financials_only_for_market_survivors():
    provider = CountingProvider(pass_market=True)
    hits = _build_screener(provider).run()
    assert len(hits) == 1
    assert hits[0].code == "688001"
    assert provider.financial_calls == 1
