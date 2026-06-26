from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from stock_mining.config import FetchConfig, OutputConfig, PipelineConfig, ScoringConfig, StateConfig, TrackConfig, UniverseConfig
from stock_mining.filters.registry import build_filters
from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension, load_dimensions_config
from stock_mining.markets.base import Market
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.pipeline.screener import DailyScreener, TrackEvaluator
from stock_mining.pipeline.single_stock import (
    ScreenMissError,
    build_live_stock_prompt,
    build_live_stock_prompt_from_project,
)
from test_pipeline import FakeProvider


def _analysis_config() -> AnalysisConfig:
    return AnalysisConfig(
        dimensions=(
            AnalysisDimension("business_model", "商业模式（1-5分）", "", 90),
            AnalysisDimension("moat", "护城河（1-5分）", "", 90),
        )
    )


def _build_screener(provider: FakeProvider) -> DailyScreener:
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
                ],
            )
        ],
        fetch=FetchConfig(use_cache=False),
        output=OutputConfig(directory="data/results"),
        scoring=ScoringConfig(),
        state=StateConfig(db_path="data/state/user_state.sqlite3"),
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


def test_build_live_prompt_for_screen_hit():
    provider = FakeProvider()
    screener = _build_screener(provider)
    result = build_live_stock_prompt(
        screener,
        "688001",
        Market.A,
        dimensions_config=_analysis_config(),
    )

    assert result.passed_screen is True
    assert result.matched_track == "profitable_growth"
    assert result.hit.code == "688001"
    assert "688001" in result.prompt
    assert "商业模式（1-5分）" in result.prompt
    assert "pe:" in result.prompt or "pe" in result.prompt


def test_build_live_prompt_without_hit_still_outputs_prompt():
    provider = FakeProvider()
    provider.snapshot = MarketSnapshot(
        code="688001",
        name="优质样本",
        market=Market.A,
        industry="专用设备",
        price=50.0,
        low_52w=10.0,
        high_52w=60.0,
        drawdown_from_high_pct=16.7,
        pe=80,
        pb=8,
        ps=10,
        dividend_yield_pct=0.1,
    )
    screener = _build_screener(provider)
    result = build_live_stock_prompt(
        screener,
        "688001",
        Market.A,
        dimensions_config=_analysis_config(),
    )

    assert result.passed_screen is False
    assert result.matched_track is None
    assert result.hit.track == "manual"
    assert "688001" in result.prompt


def test_require_hit_raises_when_stock_misses_screen():
    provider = FakeProvider()
    provider.snapshot = MarketSnapshot(
        code="688001",
        name="优质样本",
        market=Market.A,
        industry="专用设备",
        price=50.0,
        low_52w=10.0,
        high_52w=60.0,
        drawdown_from_high_pct=16.7,
        pe=80,
        pb=8,
        ps=10,
        dividend_yield_pct=0.1,
    )
    screener = _build_screener(provider)

    with pytest.raises(ScreenMissError, match="未通过"):
        build_live_stock_prompt(
            screener,
            "688001",
            Market.A,
            dimensions_config=_analysis_config(),
            require_hit=True,
        )


def test_build_live_prompt_from_project_config(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    provider.financials = StockFinancials(
        "688001",
        annual=[
            AnnualMetrics(date(2024, 12, 31), net_profit_yuan=1e8, roe_pct=15),
        ],
    )

    screener = _build_screener(provider)

    def fake_load_live_screener(config_path, *, use_cache=None):
        return screener

    monkeypatch.setattr(
        "stock_mining.pipeline.single_stock.load_live_screener",
        fake_load_live_screener,
    )

    result = build_live_stock_prompt_from_project(
        root,
        "688001",
        Market.A,
        require_hit=False,
    )
    dimensions = load_dimensions_config(root / "config" / "analysis_dimensions.yaml")
    assert any(dim.label in result.prompt for dim in dimensions.dimensions)


def test_print_prompt_cli(monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    screener = _build_screener(provider)

    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "stock_mining.pipeline.single_stock.load_live_screener",
        lambda *_args, **_kwargs: screener,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["print_prompt.py", "688001", "--meta"],
    )

    from scripts.print_prompt import main

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "688001" in captured.out
    assert "筛选:通过" in captured.out
    assert "商业模式" in captured.out or "护城河" in captured.out
