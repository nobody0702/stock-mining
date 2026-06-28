from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.llm.jiquer_client import ChatResponse, JiquerClient, JiquerClientConfig
from stock_mining.llm.stock_analyzer import analyze_from_live_prompt, format_result_table
from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit
from stock_mining.pipeline.single_stock import LivePromptResult


@pytest.fixture
def dimensions():
    root = Path(__file__).resolve().parents[1]
    return load_dimensions_config(root / "config" / "analysis_dimensions.yaml")


@pytest.fixture
def fixture_markdown():
    path = Path(__file__).resolve().parent / "fixtures" / "deepseek_analysis_response.md"
    return path.read_text(encoding="utf-8")


def test_analyze_from_live_prompt_parses_six_dimensions(dimensions, fixture_markdown):
    hit = CandidateHit("600519", "贵州茅台", Market.A, "manual", 80.0, {})
    live = LivePromptResult(
        hit=hit,
        prompt="test prompt",
        passed_screen=False,
        matched_track=None,
    )
    client = MagicMock(spec=JiquerClient)
    client.chat.return_value = ChatResponse(content=fixture_markdown)

    result = analyze_from_live_prompt(
        live,
        dimensions_config=dimensions,
        client=client,
    )
    assert len(result.parsed) == 6
    assert not result.missing
    assert "4分" in result.parsed["business_model"]

    table = format_result_table(result, dimensions)
    assert "商业模式（1-5分）" in table
    assert "贵州茅台" in table


def test_analyze_missing_dimensions(dimensions):
    hit = CandidateHit("600519", "贵州茅台", Market.A, "manual", 80.0, {})
    live = LivePromptResult(hit=hit, prompt="p", passed_screen=False, matched_track=None)
    client = MagicMock(spec=JiquerClient)
    client.chat.return_value = ChatResponse(content="| 维度 | 内容 |\n| --- | --- |\n| 商业模式（1-5分） | 3分，x |")

    result = analyze_from_live_prompt(live, dimensions_config=dimensions, client=client)
    assert result.missing
    assert "business_model" not in result.missing or len(result.missing) == 5


def test_load_llm_config():
    from stock_mining.llm.llm_config import load_llm_config

    root = Path(__file__).resolve().parents[1]
    cfg = load_llm_config(root / "config" / "llm.yaml")
    assert cfg.jiquer.model == "deepseek"
    assert cfg.jiquer.thinking_extra_body["thinking"]["type"] == "enabled"
    assert cfg.web_context.enable_notices is True
