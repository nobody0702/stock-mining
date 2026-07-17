"""Tests for the live prompt-query service and Streamlit page helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_mining.config import (
    FetchConfig,
    OutputConfig,
    PipelineConfig,
    ScoringConfig,
    StateConfig,
    TrackConfig,
    UniverseConfig,
)
from stock_mining.filters.registry import build_filters
from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
from stock_mining.markets.base import Market
from stock_mining.pipeline.screener import DailyScreener, TrackEvaluator
from stock_mining.web.prompt_query_service import (
    DEFAULT_SCREEN_CONFIG,
    HK_SCREEN_CONFIG,
    PromptQueryError,
    PromptQueryResult,
    normalize_query_input,
    parse_query_market,
    query_live_prompt,
    resolve_screen_config_for_market,
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


def test_normalize_query_input_strips_and_rejects_empty():
    assert normalize_query_input("  600519  ") == "600519"
    with pytest.raises(PromptQueryError, match="请输入"):
        normalize_query_input("   ")
    with pytest.raises(PromptQueryError, match="请输入"):
        normalize_query_input(None)


def test_parse_query_market_accepts_a_and_h_aliases():
    assert parse_query_market("a") == Market.A
    assert parse_query_market("A股") == Market.A
    assert parse_query_market("h") == Market.HK
    assert parse_query_market("hk") == Market.HK
    assert parse_query_market("港股") == Market.HK
    assert parse_query_market(Market.A) == Market.A


def test_parse_query_market_rejects_unsupported():
    with pytest.raises(PromptQueryError, match="仅支持"):
        parse_query_market("u")
    with pytest.raises(PromptQueryError, match="仅支持"):
        parse_query_market("xx")


def test_resolve_screen_config_for_market_defaults_hk():
    assert resolve_screen_config_for_market(Market.A) == DEFAULT_SCREEN_CONFIG
    assert resolve_screen_config_for_market(Market.HK) == HK_SCREEN_CONFIG
    assert (
        resolve_screen_config_for_market(Market.HK, "config/custom.yaml")
        == "config/custom.yaml"
    )


def test_query_live_prompt_by_code(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    screener = _build_screener(provider)
    logs: list[str] = []

    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_live_screener",
        lambda *_a, **_k: screener,
    )
    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_dimensions_config",
        lambda *_a, **_k: _analysis_config(),
    )

    result = query_live_prompt(
        root,
        market="a",
        query="688001",
        progress=logs.append,
    )

    assert isinstance(result, PromptQueryResult)
    assert result.code == "688001"
    assert result.name == "优质样本"
    assert "商业模式" in result.prompt
    assert any("解析" in line for line in logs)
    assert any("查询完成" in line for line in result.progress_log)
    assert "筛选:" in result.meta_line


def test_query_live_prompt_by_name(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    screener = _build_screener(provider)

    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_live_screener",
        lambda *_a, **_k: screener,
    )
    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_dimensions_config",
        lambda *_a, **_k: _analysis_config(),
    )

    result = query_live_prompt(root, market="a", query="优质样本")
    assert result.code == "688001"
    assert result.passed_screen is True


def test_query_live_prompt_unknown_stock(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    screener = _build_screener(provider)

    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_live_screener",
        lambda *_a, **_k: screener,
    )
    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_dimensions_config",
        lambda *_a, **_k: _analysis_config(),
    )

    with pytest.raises(PromptQueryError, match="未找到"):
        query_live_prompt(root, market="a", query="999999")


def test_query_live_prompt_empty_input(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(PromptQueryError, match="请输入"):
        query_live_prompt(root, market="a", query="  ")


def test_query_live_prompt_missing_config(tmp_path):
    with pytest.raises(PromptQueryError, match="找不到筛选配置"):
        query_live_prompt(
            tmp_path,
            market="a",
            query="600519",
            screen_config="missing.yaml",
        )


def test_query_live_prompt_market_not_in_screener(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    provider = FakeProvider()
    screener = _build_screener(provider)

    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.load_live_screener",
        lambda *_a, **_k: screener,
    )
    monkeypatch.setattr(
        "stock_mining.web.prompt_query_service.resolve_screen_config_for_market",
        lambda market, config_arg=DEFAULT_SCREEN_CONFIG: DEFAULT_SCREEN_CONFIG,
    )

    with pytest.raises(PromptQueryError, match="未启用市场"):
        query_live_prompt(root, market="h", query="00700")


def test_prompt_query_app_copy_button_uses_st_iframe():
    from stock_mining.web import prompt_query_app

    recorded: list[dict] = []

    def fake_iframe(body, *, height, width="stretch"):
        recorded.append({"body": body, "height": height, "width": width})

    with patch.object(prompt_query_app.st, "iframe", side_effect=fake_iframe):
        prompt_query_app._copy_prompt_button("hello prompt", element_key="k1")

    assert len(recorded) == 1
    assert "hello prompt" in recorded[0]["body"]
    assert recorded[0]["height"] == prompt_query_app.COPY_BUTTON_IFRAME_HEIGHT


def test_prompt_query_app_run_query_success_stores_result():
    from stock_mining.web import prompt_query_app

    fake_result = PromptQueryResult(
        market=Market.A,
        code="600519",
        name="贵州茅台",
        prompt="PROMPT",
        passed_screen=True,
        matched_track="profitable_growth",
        progress_log=("ok",),
    )
    state: dict = {}
    writes: list[str] = []

    status = MagicMock()
    status.write = writes.append
    status.update = MagicMock()

    with (
        patch.object(prompt_query_app.st, "session_state", state),
        patch.object(prompt_query_app.st, "status", return_value=status),
        patch.object(
            prompt_query_app,
            "query_live_prompt",
            return_value=fake_result,
        ) as query,
    ):
        prompt_query_app._run_query("a", "600519")

    query.assert_called_once()
    assert state[prompt_query_app._RESULT_KEY] is fake_result
    assert state[prompt_query_app._ERROR_KEY] is None
    assert state[prompt_query_app._COUNTER_KEY] == 1
    status.update.assert_called_with(label="查询完成", state="complete")


def test_prompt_query_app_run_query_error_clears_result():
    from stock_mining.web import prompt_query_app

    state: dict = {prompt_query_app._RESULT_KEY: "old"}
    status = MagicMock()

    with (
        patch.object(prompt_query_app.st, "session_state", state),
        patch.object(prompt_query_app.st, "status", return_value=status),
        patch.object(
            prompt_query_app,
            "query_live_prompt",
            side_effect=PromptQueryError("未找到股票代码: a:999999"),
        ),
    ):
        prompt_query_app._run_query("a", "999999")

    assert state[prompt_query_app._RESULT_KEY] is None
    assert "未找到" in state[prompt_query_app._ERROR_KEY]
    status.update.assert_called_with(label="查询失败", state="error")


def test_prompt_query_app_render_result_shows_copy_and_download():
    from stock_mining.web import prompt_query_app

    result = PromptQueryResult(
        market=Market.A,
        code="600519",
        name="贵州茅台",
        prompt="PROMPT BODY",
        passed_screen=False,
        matched_track=None,
    )
    iframe_calls: list[str] = []
    download_kwargs: list[dict] = []

    with (
        patch.object(prompt_query_app.st, "success"),
        patch.object(prompt_query_app.st, "caption"),
        patch.object(
            prompt_query_app.st,
            "iframe",
            side_effect=lambda body, **kw: iframe_calls.append(body),
        ),
        patch.object(
            prompt_query_app.st,
            "download_button",
            side_effect=lambda *a, **kw: download_kwargs.append(kw),
        ),
        patch.object(prompt_query_app.st, "expander") as expander,
        patch.object(prompt_query_app.st, "text_area"),
    ):
        expander.return_value.__enter__ = MagicMock(return_value=None)
        expander.return_value.__exit__ = MagicMock(return_value=False)
        prompt_query_app._render_result(result, copy_seq=3)

    assert len(iframe_calls) == 1
    assert "PROMPT BODY" in iframe_calls[0]
    assert download_kwargs[0]["on_click"] == "ignore"
    assert "a_600519" in download_kwargs[0]["file_name"]


def test_serve_prompt_query_script_points_to_app():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "serve_prompt_query.py").read_text(encoding="utf-8")
    assert "prompt_query_app.py" in script
    assert (root / "stock_mining" / "web" / "prompt_query_app.py").is_file()
