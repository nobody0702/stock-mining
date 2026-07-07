from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stock_mining.data.base import MarketDataProvider
from stock_mining.llm.dimensions import AnalysisConfig, load_dimensions_config
from stock_mining.llm.prompt_builder import build_stock_prompt
from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.markets.providers import build_market_providers
from stock_mining.models import CandidateHit, StockInfo
from stock_mining.pipeline.screener import DailyScreener


class ScreenMissError(Exception):
    """Raised when --require-hit is set but the stock fails screen.yaml rules."""


@dataclass(frozen=True)
class LivePromptResult:
    hit: CandidateHit
    prompt: str
    passed_screen: bool
    matched_track: str | None


def load_live_screener(
    config_path: str | Path,
    *,
    use_cache: bool | None = None,
) -> DailyScreener:
    """Build a screener for live single-stock fetch without touching user state."""
    path = Path(config_path)
    screener = DailyScreener.from_yaml(path, use_state_store=False)
    if use_cache is None or use_cache == screener.config.fetch.use_cache:
        return screener

    screener.config.fetch.use_cache = use_cache
    fetch = screener.config.fetch
    screener.providers = build_market_providers(
        screener.config.data_source,
        screener.config.markets,
        use_cache=fetch.use_cache,
        cache_dir=fetch.cache_dir,
        cache_ttl_hours=fetch.cache_ttl_hours,
        request_interval_sec=fetch.request_interval_sec,
        snapshot_workers=fetch.snapshot_workers,
    )
    return screener


def _lookback_years(screener: DailyScreener) -> int:
    for spec in screener.config.common_filters:
        if spec.get("type") == "non_declining_industry":
            return int(spec.get("lookback_years", 3))
    return 3


def build_live_stock_prompt(
    screener: DailyScreener,
    code: str,
    market: Market = Market.A,
    *,
    dimensions_config: AnalysisConfig,
    require_hit: bool = False,
    fast_fetch: bool = True,
    progress: Callable[[str], None] | None = None,
) -> LivePromptResult:
    """Fetch live data for one stock and build the same prompt as the review web UI."""
    def _log(message: str) -> None:
        if progress is not None:
            progress(message)

    if market not in screener.providers:
        config_hint = "config/screen_hk.yaml" if market == Market.HK else "screen.yaml 的 markets"
        raise ValueError(
            f"配置未启用市场 {market.value}，请使用 --config {config_hint} "
            f"（港股: python3 scripts/print_prompt.py 00700 --market h --meta）"
        )

    normalized = normalize_stock_code(code, market)
    provider = screener.providers[market]
    resolved_name = _resolve_display_name(provider, normalized) or normalized

    _log(f"正在拉取 {market.value.upper()}:{normalized} 行情…")
    snapshot = provider.fetch_stock_snapshot(
        normalized,
        resolved_name,
        include_dividend=False,
        fast=fast_fetch,
    )
    if snapshot is None:
        raise ValueError(f"无法获取 {market.value}:{normalized} 的行情快照")

    stock = StockInfo(
        code=snapshot.code,
        name=snapshot.name or normalized,
        market=market,
    )

    lookback_years = _lookback_years(screener)
    industry_returns = (
        provider.fetch_industry_returns(lookback_years)
        if screener._needs_industry_returns
        else {}
    )

    if screener._needs_industry_field and snapshot.industry is None:
        snapshot = provider.enrich_snapshot_industry(snapshot)

    _log(f"正在拉取 {stock.name} 财务数据…")
    financials = provider.fetch_financials(normalized, fast=fast_fetch)
    ctx = screener._build_context(stock, snapshot, industry_returns, financials)
    matched_track = screener._match_track(ctx)

    if require_hit and matched_track is None:
        raise ScreenMissError(f"{market.value}:{normalized} 未通过 screen.yaml 筛选")

    track = matched_track or "manual"
    hit = screener._candidate_hit(ctx, track, market)
    _log("正在生成提示词…")
    prompt = build_stock_prompt(hit, dimensions_config)
    return LivePromptResult(
        hit=hit,
        prompt=prompt,
        passed_screen=matched_track is not None,
        matched_track=matched_track,
    )


def _resolve_display_name(provider: MarketDataProvider, code: str) -> str | None:
    for stock in provider.list_stocks():
        if stock.code == code:
            return stock.name
    return None


def build_live_stock_prompt_from_project(
    root: Path,
    code: str,
    market: Market = Market.A,
    *,
    screen_config: str = "config/screen.yaml",
    dimensions_config: str = "config/analysis_dimensions.yaml",
    require_hit: bool = False,
    use_cache: bool | None = None,
    fast_fetch: bool = True,
    progress: Callable[[str], None] | None = None,
) -> LivePromptResult:
    """Convenience wrapper using default project config paths."""
    screen_path = root / screen_config
    dimensions_path = root / dimensions_config
    screener = load_live_screener(screen_path, use_cache=use_cache)
    analysis = load_dimensions_config(dimensions_path)
    return build_live_stock_prompt(
        screener,
        code,
        market,
        dimensions_config=analysis,
        require_hit=require_hit,
        fast_fetch=fast_fetch,
        progress=progress,
    )
