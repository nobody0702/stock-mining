from __future__ import annotations

from stock_mining.llm.dimensions import AnalysisDimension, AnalysisConfig
from stock_mining.llm.prompt_builder import build_stock_prompt
from stock_mining.llm.table_parser import parse_markdown_table
from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit


def test_prompt_builder_contains_dimensions():
    hit = CandidateHit("688001", "样本", Market.A, "profitable_growth", 80, {"pe": 15})
    config = AnalysisConfig(
        dimensions=(
            AnalysisDimension("business_model", "怎么赚钱（1-5分）", "hint", 90),
            AnalysisDimension("moat", "护城河有多深（1-5分）", "", 90),
        )
    )
    prompt = build_stock_prompt(hit, config)
    assert "怎么赚钱" in prompt
    assert "688001" in prompt
    assert "N分，说明" in prompt
    assert "打分规则" in prompt


def test_table_parser_matches_labels():
    text = """
| 维度 | 内容 |
| --- | --- |
| 怎么赚钱（1-5分） | 4分，卖软件给企业，订阅收费 |
| 护城河有多深（1-5分） | 4分，客户切换成本高 |
"""
    dimensions = (
        AnalysisDimension("business_model", "怎么赚钱（1-5分）", "", 90),
        AnalysisDimension("moat", "护城河有多深（1-5分）", "", 90),
    )
    parsed = parse_markdown_table(text, dimensions)
    assert "4分" in parsed["business_model"]
    assert "4分" in parsed["moat"]
