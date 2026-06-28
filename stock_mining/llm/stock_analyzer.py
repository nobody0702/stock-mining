from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from stock_mining.llm.dimensions import AnalysisConfig
from stock_mining.llm.jiquer_client import JiquerClient
from stock_mining.llm.table_parser import missing_dimensions, parse_markdown_table
from stock_mining.models import CandidateHit
from stock_mining.pipeline.single_stock import LivePromptResult, build_live_stock_prompt
from stock_mining.pipeline.screener import DailyScreener

SYSTEM_PROMPT = (
    "你是 A 股基本面分析助手。"
    "严格按用户要求输出 Markdown 表格，第一列「维度」，第二列「内容」。"
    "每个维度必须以「N分，」开头（N 为 1-5 整数），并用几句大白话说明。"
    "不要输出表格以外的多余章节。"
)


@dataclass(frozen=True)
class AnalysisResult:
    hit: CandidateHit
    prompt: str
    raw_response: str
    parsed: dict[str, str]
    missing: list[str]
    reasoning_content: str | None
    passed_screen: bool
    matched_track: str | None
    web_context: str = ""


def analyze_stock(
    screener: DailyScreener,
    code: str,
    market,
    *,
    dimensions_config: AnalysisConfig,
    client: JiquerClient,
    thinking: bool = False,
    web_search: bool = False,
    jiquer_native_search: bool = False,
    web_context_text: str = "",
    fast_fetch: bool = True,
    progress: Callable[[str], None] | None = None,
) -> AnalysisResult:
    live = build_live_stock_prompt(
        screener,
        code,
        market,
        dimensions_config=dimensions_config,
        require_hit=False,
        fast_fetch=fast_fetch,
        progress=progress,
    )
    return analyze_from_live_prompt(
        live,
        dimensions_config=dimensions_config,
        client=client,
        thinking=thinking,
        web_search=jiquer_native_search,
        web_context_text=web_context_text,
    )


def analyze_from_live_prompt(
    live: LivePromptResult,
    *,
    dimensions_config: AnalysisConfig,
    client: JiquerClient,
    thinking: bool = False,
    web_search: bool = False,
    web_context_text: str = "",
) -> AnalysisResult:
    user_content = live.prompt
    if web_context_text:
        user_content = live.prompt + web_context_text
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    response = client.chat(messages, thinking=thinking, web_search=web_search)
    parsed = parse_markdown_table(response.content, dimensions_config.dimensions)
    missing = missing_dimensions(parsed, dimensions_config.dimensions)
    return AnalysisResult(
        hit=live.hit,
        prompt=user_content,
        raw_response=response.content,
        parsed=parsed,
        missing=missing,
        reasoning_content=response.reasoning_content,
        passed_screen=live.passed_screen,
        matched_track=live.matched_track,
        web_context=web_context_text,
    )


def format_result_table(
    result: AnalysisResult,
    dimensions_config: AnalysisConfig,
) -> str:
    lines = [
        f"# {result.hit.name} ({result.hit.market.value.upper()}:{result.hit.code})",
        "",
        "| 维度 | 内容 |",
        "| --- | --- |",
    ]
    for dimension in dimensions_config.dimensions:
        cell = result.parsed.get(dimension.id, "—")
        lines.append(f"| {dimension.label} | {cell} |")
    return "\n".join(lines)
