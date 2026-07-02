from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stock_mining.markets.base import Market
from stock_mining.markets.market_scope import market_in_selection
from stock_mining.markets.stock_key import parse_stock_input
from stock_mining.models import CandidateHit
from stock_mining.pipeline.screener import DailyScreener, run_unified_screeners_for_market
from stock_mining.state.store import UserStateStore
from stock_mining.strategies import (
    MINING_STRATEGIES,
    ScreenStrategy,
    get_strategy,
    parse_strategy_selection,
    resolve_config_path,
)


@dataclass(frozen=True)
class ScreenRunResult:
    strategy_id: str
    strategy_label: str
    markets: list[Market]
    hits: list[CandidateHit]
    json_path: Path
    csv_path: Path
    legacy_path: Path


def _codes_for_market(
    raw_codes: list[str] | None,
    market: Market,
    *,
    default_market: Market,
) -> list[str] | None:
    if not raw_codes:
        return None
    selected: list[str] = []
    for token in raw_codes:
        token_market, bare = parse_stock_input(token, default_market=default_market)
        if token_market != market:
            continue
        selected.append(bare)
    return selected or None


def _build_screener(
    root: Path,
    strategy: ScreenStrategy,
    *,
    market: Market,
    state_store: UserStateStore | None,
    max_stocks: int | None,
    codes: list[str] | None,
    top_n: int | None,
    config_override: Path | None,
) -> DailyScreener:
    config_path = config_override or resolve_config_path(root, strategy.id)
    screener = DailyScreener.from_yaml(config_path, state_store=state_store)
    screener.config.markets = [market]

    from stock_mining.markets.providers import build_market_providers

    screener.providers = build_market_providers(
        screener.config.data_source,
        [market],
        use_cache=screener.config.fetch.use_cache,
        cache_dir=screener.config.fetch.cache_dir,
        cache_ttl_hours=screener.config.fetch.cache_ttl_hours,
        request_interval_sec=screener.config.fetch.request_interval_sec,
        snapshot_workers=screener.config.fetch.snapshot_workers,
    )

    if max_stocks is not None:
        screener.config.universe.max_stocks = max_stocks
    if top_n is not None:
        screener.config.output.top_n = top_n

    if codes:
        market_codes = _codes_for_market(codes, market, default_market=market)
        screener.config.universe.codes = market_codes

    return screener


def _finalize_strategy_result(
    strategy: ScreenStrategy,
    market: Market,
    screener: DailyScreener,
    hits: list[CandidateHit],
) -> ScreenRunResult:
    for hit in hits:
        hit.metrics["source_strategy"] = strategy.id

    json_path, csv_path, legacy_path = screener.save(hits)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["strategy"] = strategy.id
    payload["strategy_label"] = strategy.label
    payload["markets"] = [market.value]
    payload["run_at"] = datetime.now().isoformat(timespec="seconds")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return ScreenRunResult(
        strategy_id=strategy.id,
        strategy_label=strategy.label,
        markets=[market],
        hits=hits,
        json_path=json_path,
        csv_path=csv_path,
        legacy_path=legacy_path,
    )


def run_strategy_screen(
    root: Path,
    strategy: ScreenStrategy,
    *,
    selected_markets: list[Market],
    state_store: UserStateStore | None,
    max_stocks: int | None = None,
    codes: list[str] | None = None,
    top_n: int | None = None,
    config_override: Path | None = None,
) -> ScreenRunResult | None:
    allowed_markets = [m for m in strategy.markets if market_in_selection(selected_markets, m)]
    if not allowed_markets:
        return None

    if len(allowed_markets) == 1:
        market = allowed_markets[0]
        screener = _build_screener(
            root,
            strategy,
            market=market,
            state_store=state_store,
            max_stocks=max_stocks,
            codes=codes,
            top_n=top_n,
            config_override=config_override,
        )
        hits = screener.run()
        return _finalize_strategy_result(strategy, market, screener, hits)

    results: list[ScreenRunResult] = []
    for market in allowed_markets:
        screener = _build_screener(
            root,
            strategy,
            market=market,
            state_store=state_store,
            max_stocks=max_stocks,
            codes=codes,
            top_n=top_n,
            config_override=config_override,
        )
        hits = screener.run()
        results.append(_finalize_strategy_result(strategy, market, screener, hits))

    if not results:
        return None
    if len(results) == 1:
        return results[0]

    merged_hits = sorted(
        (hit for result in results for hit in result.hits),
        key=lambda item: item.score,
        reverse=True,
    )
    return ScreenRunResult(
        strategy_id=results[0].strategy_id,
        strategy_label=results[0].strategy_label,
        markets=allowed_markets,
        hits=merged_hits,
        json_path=results[0].json_path,
        csv_path=results[0].csv_path,
        legacy_path=results[0].legacy_path,
    )


def _run_unified_market_screen(
    root: Path,
    market: Market,
    job_ids: list[str],
    *,
    state_store: UserStateStore | None,
    max_stocks: int | None,
    codes: list[str] | None,
    top_n: int | None,
    config_override: Path | None,
) -> list[ScreenRunResult]:
    entries: list[tuple[ScreenStrategy, DailyScreener]] = []
    for job_id in job_ids:
        strategy = get_strategy(job_id)
        if market not in strategy.markets:
            continue
        override = config_override if job_id == job_ids[0] and len(job_ids) == 1 else None
        screener = _build_screener(
            root,
            strategy,
            market=market,
            state_store=state_store,
            max_stocks=max_stocks,
            codes=codes,
            top_n=top_n,
            config_override=override,
        )
        entries.append((strategy, screener))

    if not entries:
        return []

    screeners = [screener for _, screener in entries]
    shared_provider = screeners[0].providers[market]
    for screener in screeners[1:]:
        screener.providers[market] = shared_provider

    hits_lists = run_unified_screeners_for_market(market, screeners)
    return [
        _finalize_strategy_result(strategy, market, screener, hits)
        for (strategy, screener), hits in zip(entries, hits_lists)
    ]


def run_mining(
    root: Path,
    *,
    strategy_id: str,
    selected_markets: list[Market],
    state_store: UserStateStore | None,
    max_stocks: int | None = None,
    codes: list[str] | None = None,
    top_n: int | None = None,
    config_override: Path | None = None,
) -> list[ScreenRunResult]:
    job_ids = parse_strategy_selection(strategy_id)

    market_jobs: dict[Market, list[str]] = {}
    for job_id in job_ids:
        strategy = get_strategy(job_id)
        for market in strategy.markets:
            if not market_in_selection(selected_markets, market):
                continue
            market_jobs.setdefault(market, [])
            if job_id not in market_jobs[market]:
                market_jobs[market].append(job_id)

    results: list[ScreenRunResult] = []
    for market, jobs in market_jobs.items():
        if len(jobs) == 1:
            strategy = get_strategy(jobs[0])
            override = config_override if len(job_ids) == 1 else None
            result = run_strategy_screen(
                root,
                strategy,
                selected_markets=[market],
                state_store=state_store,
                max_stocks=max_stocks,
                codes=codes,
                top_n=top_n,
                config_override=override,
            )
            if result is not None:
                results.append(result)
        else:
            results.extend(
                _run_unified_market_screen(
                    root,
                    market,
                    jobs,
                    state_store=state_store,
                    max_stocks=max_stocks,
                    codes=codes,
                    top_n=top_n,
                    config_override=config_override,
                )
            )

    if set(job_ids) == set(MINING_STRATEGIES.keys()) and results:
        _write_merged_all_candidates(root, results)

    return results


def _write_merged_all_candidates(root: Path, results: list[ScreenRunResult]) -> Path:
    merged_hits: list[CandidateHit] = []
    for result in results:
        merged_hits.extend(result.hits)
    merged_hits.sort(key=lambda item: item.score, reverse=True)

    output_dir = root / "data" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "all_candidates.json"
    payload = {
        "strategy": "all",
        "strategy_label": "所有策略合并",
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "top_n": None,
        "count": len(merged_hits),
        "sources": [result.strategy_id for result in results],
        "candidates": [hit.to_dict() for hit in merged_hits],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path
