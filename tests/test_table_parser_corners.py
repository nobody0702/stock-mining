from __future__ import annotations

from stock_mining.llm.dimensions import AnalysisDimension
from stock_mining.llm.table_parser import missing_dimensions, parse_markdown_table


DIMS = (
    AnalysisDimension("business_model", "怎么赚钱（1-5分）", "", 90),
    AnalysisDimension("moat", "护城河有多深（1-5分）", "", 90),
    AnalysisDimension("why_cheap", "为什么现在便宜（1-5分）", "", 30),
)


def test_parse_empty_text_returns_empty():
    assert parse_markdown_table("", DIMS) == {}


def test_parse_ignores_separator_row():
    text = """
| 维度 | 内容 |
| --- | --- |
| 怎么赚钱（1-5分） | 4分，卖水 |
"""
    parsed = parse_markdown_table(text, DIMS)
    assert parsed == {"business_model": "4分，卖水"}


def test_parse_skips_rows_with_empty_content():
    text = """
| 维度 | 内容 |
| --- | --- |
| 怎么赚钱（1-5分） | |
| 为什么现在便宜（1-5分） | 3分，情绪错杀 |
"""
    parsed = parse_markdown_table(text, DIMS)
    assert "business_model" not in parsed
    assert parsed["why_cheap"] == "3分，情绪错杀"


def test_parse_accepts_dimension_id_as_label():
    text = """
| 维度 | 内容 |
| --- | --- |
| business_model | 订阅制 SaaS |
"""
    parsed = parse_markdown_table(text, DIMS)
    assert parsed["business_model"] == "订阅制 SaaS"


def test_parse_fuzzy_label_match():
    text = """
| 维度 | 内容 |
| --- | --- |
| 护城河有多深（1-5分） | 4分，品牌+渠道 |
"""
    parsed = parse_markdown_table(text, DIMS)
    assert parsed["moat"] == "4分，品牌+渠道"


def test_missing_dimensions_lists_all_absent():
    parsed = {"business_model": "xxx"}
    missing = missing_dimensions(parsed, DIMS)
    assert "moat" in missing
    assert "why_cheap" in missing
    assert "business_model" not in missing


def test_parse_multiline_table_with_extra_columns():
    text = """
| 维度 | 内容 | 备注 |
| --- | --- | --- |
| 怎么赚钱（1-5分） | 5分，卖芯片 | ignore |
"""
    parsed = parse_markdown_table(text, DIMS)
    assert parsed["business_model"] == "5分，卖芯片"
