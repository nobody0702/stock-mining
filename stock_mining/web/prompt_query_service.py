"""Live single-stock prompt query for the Streamlit prompt-query page.

Wraps the same pipeline as ``scripts/print_prompt.py``, plus name→code
resolution, without touching the review UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.llm.stock_resolver import StockResolveError, resolve_stock_inputs
from stock_mining.markets.base import Market, parse_market
from stock_mining.pipeline.single_stock import (
    LivePromptResult,
    build_live_stock_prompt,
    load_live_screener,
)

DEFAULT_SCREEN_CONFIG = "config/screen.yaml"
HK_SCREEN_CONFIG = "config/screen_hk.yaml"
DEFAULT_DIMENSIONS_CONFIG = "config/analysis_dimensions.yaml"

ProgressFn = Callable[[str], None]


class PromptQueryError(Exception):
    """User-facing error for empty/invalid input or failed lookups."""


@dataclass(frozen=True)
class PromptQueryResult:
    market: Market
    code: str
    name: str
    prompt: str
    passed_screen: bool
    matched_track: str | None
    progress_log: tuple[str, ...] = field(default_factory=tuple)

    @property
    def stock_key(self) -> str:
        return f"{self.market.value}:{self.code}"

    @property
    def meta_line(self) -> str:
        track = self.matched_track or "未通过筛选"
        status = "通过" if self.passed_screen else "未通过"
        return (
            f"{self.name} ({self.market.value.upper()}:{self.code}) "
            f"筛选:{status} 轨道:{track}"
        )


def normalize_query_input(raw: str | None) -> str:
    """Strip user input; raise if empty."""
    text = (raw or "").strip()
    if not text:
        raise PromptQueryError("请输入股票代码或名称，例如 600519 或 贵州茅台")
    return text


def parse_query_market(raw: str | Market) -> Market:
    """Only A / H are supported on the prompt-query page."""
    if isinstance(raw, Market):
        market = raw
    else:
        token = (raw or "").strip().lower()
        if token in {"hk", "港股", "h股"}:
            token = "h"
        if token in {"a股", "沪深"}:
            token = "a"
        try:
            market = parse_market(token)
        except Exception as exc:
            raise PromptQueryError("市场仅支持 a（A股）或 h（港股）") from exc
    if market not in {Market.A, Market.HK}:
        raise PromptQueryError("市场仅支持 a（A股）或 h（港股）")
    return market


def resolve_screen_config_for_market(market: Market, config_arg: str = DEFAULT_SCREEN_CONFIG) -> str:
    """Mirror print_prompt: HK defaults to screen_hk.yaml when config is left as A-share default."""
    normalized = config_arg.replace("\\", "/")
    if market == Market.HK and normalized == DEFAULT_SCREEN_CONFIG:
        return HK_SCREEN_CONFIG
    return config_arg


def query_live_prompt(
    root: Path,
    *,
    market: str | Market,
    query: str,
    progress: ProgressFn | None = None,
    screen_config: str = DEFAULT_SCREEN_CONFIG,
    dimensions_config: str = DEFAULT_DIMENSIONS_CONFIG,
    require_hit: bool = False,
    use_cache: bool | None = None,
    fast_fetch: bool = True,
) -> PromptQueryResult:
    """Resolve name/code, fetch live data, and build the Cursor analysis prompt."""
    log: list[str] = []

    def _log(message: str) -> None:
        log.append(message)
        if progress is not None:
            progress(message)

    market_value = parse_query_market(market)
    token = normalize_query_input(query)
    screen_rel = resolve_screen_config_for_market(market_value, screen_config)
    screen_path = root / screen_rel if not Path(screen_rel).is_absolute() else Path(screen_rel)
    dimensions_path = (
        root / dimensions_config
        if not Path(dimensions_config).is_absolute()
        else Path(dimensions_config)
    )

    if not screen_path.is_file():
        raise PromptQueryError(f"找不到筛选配置: {screen_path}")
    if not dimensions_path.is_file():
        raise PromptQueryError(f"找不到分析维度配置: {dimensions_path}")

    _log(f"正在加载配置（{screen_path.name}）…")
    try:
        screener = load_live_screener(screen_path, use_cache=use_cache)
    except Exception as exc:
        raise PromptQueryError(f"加载筛选配置失败: {exc}") from exc

    if market_value not in screener.providers:
        raise PromptQueryError(
            f"配置未启用市场 {market_value.value}，请检查 {screen_path.name}"
        )

    provider = screener.providers[market_value]
    _log("正在解析股票代码/名称…")
    try:
        resolved = resolve_stock_inputs(
            [token],
            market=market_value,
            list_stocks_fn=provider.list_stocks,
        )[0]
    except StockResolveError as exc:
        raise PromptQueryError(str(exc)) from exc

    _log(f"已定位：{resolved.name} ({resolved.market.value.upper()}:{resolved.code})")

    analysis = load_dimensions_config(dimensions_path)
    try:
        live: LivePromptResult = build_live_stock_prompt(
            screener,
            resolved.code,
            market_value,
            dimensions_config=analysis,
            require_hit=require_hit,
            fast_fetch=fast_fetch,
            progress=_log,
        )
    except ValueError as exc:
        raise PromptQueryError(str(exc)) from exc
    except Exception as exc:
        raise PromptQueryError(f"生成 Prompt 失败: {exc}") from exc

    _log("查询完成")
    return PromptQueryResult(
        market=live.hit.market,
        code=live.hit.code,
        name=live.hit.name,
        prompt=live.prompt,
        passed_screen=live.passed_screen,
        matched_track=live.matched_track,
        progress_log=tuple(log),
    )
