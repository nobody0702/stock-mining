from __future__ import annotations

from datetime import date

from stock_mining.config import (
    FetchConfig,
    OutputConfig,
    PipelineConfig,
    ScoringConfig,
    StateConfig,
    TrackConfig,
    UniverseConfig,
)
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.pipeline.prefilter import soft_passes_valuation, track_soft_passes_market
from stock_mining.pipeline.screener import DailyScreener, TrackEvaluator
from stock_mining.models import ScreeningContext


class LayeredCountingProvider(MarketDataProvider):
    """Simulates bulk price row → optional enrich → financial fetch."""

    def __init__(self) -> None:
        self.enrich_calls: list[str] = []
        self.financial_calls: list[str] = []
        self._price = {
            "00700": MarketSnapshot(
                code="00700",
                name="腾讯",
                market=Market.HK,
                price=100.0,
                low_52w=95.0,
                high_52w=150.0,
            ),
            "00001": MarketSnapshot(
                code="00001",
                name="远高",
                market=Market.HK,
                price=200.0,
                low_52w=100.0,
                high_52w=250.0,
            ),
            "00999": MarketSnapshot(
                code="00999",
                name="低估值",
                market=Market.HK,
                price=10.0,
                low_52w=9.5,
                high_52w=20.0,
            ),
        }
        self._enriched = {
            "00700": MarketSnapshot(
                code="00700",
                name="腾讯",
                market=Market.HK,
                price=100.0,
                low_52w=95.0,
                high_52w=150.0,
                pe=15.0,
                pb=1.5,
                ps=2.0,
                dividend_yield_pct=1.2,
            ),
            "00999": MarketSnapshot(
                code="00999",
                name="低估值",
                market=Market.HK,
                price=10.0,
                low_52w=9.5,
                high_52w=20.0,
                pe=100.0,
                pb=8.0,
                ps=10.0,
                dividend_yield_pct=0.1,
            ),
        }
        self._financials = {
            "00700": StockFinancials(
                "00700",
                market=Market.HK,
                annual=[
                    AnnualMetrics(
                        date(2024, 12, 31),
                        net_profit_yuan=2e8,
                        revenue_yuan=5e8,
                        gross_margin_pct=40,
                        net_margin_pct=22,
                        debt_ratio_pct=30,
                        roe_pct=12,
                        operating_cashflow_per_share=1.0,
                    )
                ],
            ),
        }

    @property
    def market(self) -> Market:
        return Market.HK

    def list_stocks(self) -> list[StockInfo]:
        return [
            StockInfo(code, snap.name, Market.HK) for code, snap in self._price.items()
        ]

    def fetch_market_snapshots(self, codes=None):
        return self.fetch_price_snapshots(codes)

    def fetch_price_snapshots(self, codes=None, *, include_52w: bool = True):
        del include_52w
        if codes is None:
            return dict(self._price)
        return {c: self._price[c] for c in codes if c in self._price}

    def enrich_snapshots(self, snapshots):
        out = {}
        for code, snap in snapshots.items():
            self.enrich_calls.append(code)
            out[code] = self._enriched.get(code, snap)
        return out

    def fetch_dividend_map(self):
        return {}

    def fetch_stock_snapshot(self, code, name, *, include_dividend=True, fast=False):
        return self._enriched.get(code) or self._price[code]

    def fetch_industry_returns(self, lookback_years: int):
        return {}

    def fetch_financials(self, code, *, fast=False):
        self.financial_calls.append(code)
        return self._financials.get(
            code,
            StockFinancials(code, market=Market.HK, annual=[]),
        )


def _hk_screener(provider: LayeredCountingProvider) -> DailyScreener:
    config = PipelineConfig(
        data_source="fake",
        markets=[Market.HK],
        universe=UniverseConfig(),
        common_filters=[
            {"name": "non_st", "type": "non_st"},
            {"name": "near_52w_low", "type": "near_52w_low", "max_price_to_low_ratio": 1.08},
        ],
        tracks=[
            TrackConfig(
                name="profitable_growth",
                filters=[
                    {"name": "roe", "type": "roe_window", "years": 1, "min_pct": 8, "high_min_pct": 10},
                    {"name": "dividend_yield", "type": "dividend_yield_min", "threshold_pct": 0.5},
                    {
                        "name": "valuation",
                        "type": "valuation_by_profit",
                        "profit_threshold_yuan": 100000000,
                        "pe_max": 25,
                        "pb_max": 3,
                        "ps_max": 5,
                    },
                ],
            ),
            TrackConfig(
                name="loss_tolerant_growth",
                filters=[
                    {
                        "name": "valuation_ps",
                        "type": "valuation_by_profit",
                        "profit_threshold_yuan": 100000000,
                        "pe_max": 80,
                        "pb_max": 5,
                        "ps_max": 8,
                    },
                ],
            ),
        ],
        fetch=FetchConfig(financial_workers=1, use_cache=False),
        output=OutputConfig(directory="data/results", top_n=10),
        scoring=ScoringConfig(),
        state=StateConfig(db_path=":memory:"),
        filters=[],
    )
    return DailyScreener(
        config,
        {Market.HK: provider},
        build_filters(config.common_filters),
        [
            TrackEvaluator(name=t.name, filters=build_filters(t.filters))
            for t in config.tracks
        ],
        state_store=None,
    )


def test_soft_passes_valuation_rejects_impossible_names():
    snap = MarketSnapshot(code="x", name="x", pe=100, pb=9, ps=12)
    assert not soft_passes_valuation(snap, pe_max=25, pb_max=3, ps_max=5)
    assert soft_passes_valuation(snap, pe_max=120, pb_max=3, ps_max=5)


def test_layered_hk_skips_enrich_and_financials_for_far_from_low():
    provider = LayeredCountingProvider()
    hits = _hk_screener(provider).run()
    # 00001 fails near_52w (ratio=2.0) → no enrich / no financials
    assert "00001" not in provider.enrich_calls
    assert "00001" not in provider.financial_calls
    # near-low names get enriched
    assert "00700" in provider.enrich_calls
    assert "00999" in provider.enrich_calls
    # 00999 soft-fails both valuation tracks → no financial fetch
    assert "00999" not in provider.financial_calls
    assert "00700" in provider.financial_calls
    assert len(hits) == 1
    assert hits[0].code == "00700"


def test_track_soft_passes_market_uses_present_dividend():
    filters = build_filters(
        [{"name": "dividend_yield", "type": "dividend_yield_min", "threshold_pct": 0.5}]
    )
    ctx_fail = ScreeningContext(
        stock=StockInfo("1", "x", Market.HK),
        market=MarketSnapshot(code="1", name="x", market=Market.HK, dividend_yield_pct=0.1),
    )
    ctx_ok = ScreeningContext(
        stock=StockInfo("1", "x", Market.HK),
        market=MarketSnapshot(code="1", name="x", market=Market.HK, dividend_yield_pct=1.0),
    )
    assert not track_soft_passes_market(ctx_fail, filters)
    assert track_soft_passes_market(ctx_ok, filters)
