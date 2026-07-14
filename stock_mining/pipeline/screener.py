from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from stock_mining.config import PipelineConfig, load_pipeline_config, resolve_project_path
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.base import Filter
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market
from stock_mining.markets.stock_key import parse_stock_input
from stock_mining.markets.providers import build_market_providers
from stock_mining.markets.snapshot_utils import snapshot_needs_price_enrichment
from stock_mining.models import CandidateHit, MarketSnapshot, ScreenHit, ScreeningContext, StockInfo
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.pipeline.funnel import (
    needs_financials,
    needs_industry_name,
    partition_filters,
    passes_filters,
    passes_without_financials,
)
from stock_mining.pipeline.prefilter import (
    is_price_only_filter,
    needs_52w_fields,
    needs_valuation_fields,
    track_soft_passes_market,
)
from stock_mining.scoring.engine import compute_score, extract_metrics
from stock_mining.state.store import UserStateStore
from stock_mining.utils import is_bj_code, is_st_name, match_industry_return


@dataclass
class TrackEvaluator:
    name: str
    filters: list[Filter]


@dataclass
class _FinancialCandidate:
    stock: StockInfo
    snapshot: MarketSnapshot


@dataclass
class _UnifiedFinancialItem:
    stock: StockInfo
    snapshot: MarketSnapshot
    screener_indices: list[int]


def _lookback_years_for_screeners(screeners: list[DailyScreener]) -> int:
    lookback_years = 3
    for screener in screeners:
        for spec in screener.config.common_filters:
            if spec.get("type") == "non_declining_industry":
                lookback_years = max(
                    lookback_years,
                    int(spec.get("lookback_years", 3)),
                )
    return lookback_years


def _fetch_price_snapshots(
    provider: MarketDataProvider,
    codes: set[str],
    *,
    include_52w: bool,
) -> dict[str, MarketSnapshot]:
    fetch_price = getattr(provider, "fetch_price_snapshots", None)
    if callable(fetch_price):
        return fetch_price(codes, include_52w=include_52w)
    return provider.fetch_market_snapshots(codes)


def _enrich_snapshots(
    provider: MarketDataProvider,
    snapshots: dict[str, MarketSnapshot],
) -> dict[str, MarketSnapshot]:
    enrich = getattr(provider, "enrich_snapshots", None)
    if callable(enrich):
        return enrich(snapshots)
    return snapshots


def _fetch_financials_cached(
    provider: MarketDataProvider,
    codes: list[str],
) -> dict:
    fetch_cached = getattr(provider, "fetch_financials_cached", None)
    if callable(fetch_cached):
        return fetch_cached(codes)
    return {}


def run_unified_screeners_for_market(
    market: Market,
    screeners: list[DailyScreener],
    *,
    universe: list[StockInfo] | None = None,
) -> list[list[CandidateHit]]:
    """Evaluate multiple screeners on one market with a single data fetch pass."""
    if not screeners:
        return []

    primary = screeners[0]
    provider = primary.providers[market]
    if universe is None:
        universe = primary.build_universe(market)

    lookback_years = _lookback_years_for_screeners(screeners)
    needs_industry_returns = any(s._needs_industry_returns for s in screeners)
    industry_returns = (
        provider.fetch_industry_returns(lookback_years) if needs_industry_returns else {}
    )

    include_52w = any(s._needs_52w for s in screeners)
    universe_codes = {stock.code for stock in universe}
    bulk_snapshots = _fetch_price_snapshots(
        provider,
        universe_codes,
        include_52w=include_52w,
    )

    # Layer 1: price-only common filters across all screeners (union of survivors).
    price_survivors: dict[str, tuple[StockInfo, MarketSnapshot]] = {}
    for stock in tqdm(universe, desc=f"price-filter-{market.value}"):
        snapshot = primary._resolve_snapshot(provider, stock, bulk_snapshots)
        if snapshot is None:
            continue
        any_alive = False
        for screener in screeners:
            ctx = screener._build_context(stock, snapshot, industry_returns)
            if screener._passes_price_common(ctx):
                any_alive = True
                break
        if any_alive:
            price_survivors[stock.code] = (stock, snapshot)

    # Layer 2: expensive valuation enrichment only for price survivors.
    if any(s._needs_valuation_enrichment for s in screeners) and price_survivors:
        to_enrich = {code: snap for code, (_stock, snap) in price_survivors.items()}
        enriched = _enrich_snapshots(provider, to_enrich)
        for code, snap in enriched.items():
            stock, _ = price_survivors[code]
            price_survivors[code] = (stock, snap)

    hits_per_screener: list[list[CandidateHit]] = [[] for _ in screeners]
    financial_queue: dict[str, _UnifiedFinancialItem] = {}

    for code, (stock, snapshot) in tqdm(
        price_survivors.items(),
        desc=f"market-filter-{market.value}",
    ):
        working_snapshot = snapshot
        if any(s._needs_industry_field for s in screeners) and working_snapshot.industry is None:
            working_snapshot = provider.enrich_snapshot_industry(working_snapshot)

        for idx, screener in enumerate(screeners):
            ctx = screener._build_context(stock, working_snapshot, industry_returns)
            if screener._common_market and not passes_filters(ctx, screener._common_market):
                continue
            if screener._common_industry and not passes_filters(ctx, screener._common_industry):
                continue

            if screener._needs_financial_fetch(ctx):
                item = financial_queue.get(stock.code)
                if item is None:
                    item = _UnifiedFinancialItem(
                        stock=stock,
                        snapshot=working_snapshot,
                        screener_indices=[],
                    )
                    financial_queue[stock.code] = item
                item.screener_indices.append(idx)
                continue

            matched_track = screener._match_track(ctx)
            if matched_track is not None:
                hits_per_screener[idx].append(
                    screener._candidate_hit(ctx, matched_track, stock.market)
                )

    workers = max(1, max(s.config.fetch.financial_workers for s in screeners))
    label = f"financial-{market.value}"

    def _evaluate_unified(
        item: _UnifiedFinancialItem,
        financials,
    ) -> list[tuple[int, CandidateHit]]:
        matched: list[tuple[int, CandidateHit]] = []
        for idx in item.screener_indices:
            screener = screeners[idx]
            ctx = screener._build_context(
                item.stock,
                item.snapshot,
                industry_returns,
                financials,
            )
            matched_track = screener._match_track(ctx)
            if matched_track is not None:
                matched.append(
                    (
                        idx,
                        screener._candidate_hit(ctx, matched_track, item.stock.market),
                    )
                )
        return matched

    if financial_queue:
        cached = _fetch_financials_cached(provider, list(financial_queue.keys()))
        pending = [item for code, item in financial_queue.items() if code not in cached]
        for code, item in financial_queue.items():
            if code not in cached:
                continue
            for idx, hit in _evaluate_unified(item, cached[code]):
                hits_per_screener[idx].append(hit)

        def _fetch_and_evaluate(item: _UnifiedFinancialItem) -> list[tuple[int, CandidateHit]]:
            return _evaluate_unified(item, provider.fetch_financials(item.stock.code))

        if pending:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_fetch_and_evaluate, item): item for item in pending
                }
                for future in tqdm(as_completed(futures), total=len(futures), desc=label):
                    for idx, hit in future.result():
                        hits_per_screener[idx].append(hit)

    for screener, hits in zip(screeners, hits_per_screener):
        hits.sort(key=lambda item: item.score, reverse=True)
        top_n = screener.config.output.top_n
        if top_n:
            del hits[top_n:]
        if screener.state_store is not None:
            trimmed = filter_candidates(
                hits,
                screener.state_store,
                drop_ratio=screener.config.state.too_expensive_drop_ratio,
            )
            hits[:] = trimmed

    return hits_per_screener


class DailyScreener:
    def __init__(
        self,
        config: PipelineConfig,
        providers: dict[Market, MarketDataProvider],
        common_filters: list[Filter],
        tracks: list[TrackEvaluator],
        state_store: UserStateStore | None = None,
    ) -> None:
        self.config = config
        self.providers = providers
        self.common_filters = common_filters
        self.tracks = tracks
        self.state_store = state_store
        self._needs_industry_returns = any(
            filter_.requires_industry_returns
            for filter_ in (
                self.common_filters + [f for track in self.tracks for f in track.filters]
            )
        )
        self._common_market, self._common_industry, self._common_financial = partition_filters(
            self.common_filters
        )
        self._common_price = [f for f in self._common_market if is_price_only_filter(f)]
        self._track_partitions = {
            track.name: partition_filters(track.filters) for track in self.tracks
        }
        all_filters = self.common_filters + [
            filter_ for track in self.tracks for filter_ in track.filters
        ]
        self._needs_industry_field = needs_industry_name(all_filters)
        self._needs_52w = needs_52w_fields(all_filters)
        self._needs_valuation_enrichment = needs_valuation_fields(all_filters)

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        state_store: UserStateStore | None = None,
        use_state_store: bool = True,
    ) -> "DailyScreener":
        config = load_pipeline_config(path)
        config_path = Path(path)
        if use_state_store and state_store is None:
            state_store = UserStateStore(
                resolve_project_path(config_path, config.state.db_path),
                dispositions_dir=resolve_project_path(
                    config_path,
                    config.state.dispositions_dir,
                ),
            )
        elif not use_state_store:
            state_store = None
        providers = build_market_providers(
            config.data_source,
            config.markets,
            use_cache=config.fetch.use_cache,
            cache_dir=config.fetch.cache_dir,
            cache_ttl_hours=config.fetch.cache_ttl_hours,
            request_interval_sec=config.fetch.request_interval_sec,
            snapshot_workers=config.fetch.snapshot_workers,
        )
        common_filters = build_filters(config.common_filters or config.filters)
        tracks = [
            TrackEvaluator(name=track.name, filters=build_filters(track.filters))
            for track in config.tracks
        ]
        if not tracks and config.filters:
            tracks = [TrackEvaluator(name="default", filters=build_filters(config.filters))]
        return cls(config, providers, common_filters, tracks, state_store)

    def build_universe(self, market: Market) -> list[StockInfo]:
        if market not in self.config.markets:
            return []
        provider = self.providers[market]
        if self.config.universe.codes:
            name_map = {item.code: item.name for item in provider.list_stocks()}
            stocks: list[StockInfo] = []
            for token in self.config.universe.codes:
                token_market, bare = parse_stock_input(token, default_market=market)
                if token_market != market:
                    continue
                stocks.append(
                    StockInfo(
                        code=bare,
                        name=name_map.get(bare, bare),
                        market=market,
                    )
                )
            return stocks

        stocks = provider.list_stocks()
        filtered: list[StockInfo] = []
        for stock in stocks:
            if market == Market.A and self.config.universe.exclude_st and is_st_name(stock.name):
                continue
            if market == Market.A and self.config.universe.exclude_bj and is_bj_code(stock.code):
                continue
            filtered.append(stock)

        max_stocks = self.config.universe.max_stocks
        if max_stocks is not None:
            filtered = filtered[: int(max_stocks)]
        return filtered

    def _build_context(
        self,
        stock: StockInfo,
        market_snapshot: MarketSnapshot | None,
        industry_returns: dict[str, float],
        financials=None,
    ) -> ScreeningContext:
        industry_return = match_industry_return(
            market_snapshot.industry if market_snapshot else None,
            industry_returns,
        )
        stock_info = stock
        if market_snapshot is not None:
            stock_info = StockInfo(
                code=market_snapshot.code,
                name=market_snapshot.name,
                market=stock.market,
            )
        return ScreeningContext(
            stock=stock_info,
            market=market_snapshot,
            financials=financials,
            industry_return_3y_pct=industry_return,
        )

    def _resolve_snapshot(
        self,
        provider: MarketDataProvider,
        stock: StockInfo,
        bulk_snapshots: dict[str, MarketSnapshot],
    ) -> MarketSnapshot | None:
        snapshot = bulk_snapshots.get(stock.code)
        if snapshot_needs_price_enrichment(snapshot):
            fetched = provider.fetch_stock_snapshot(stock.code, stock.name)
            if fetched.price is not None:
                return fetched
            return fetched if snapshot is None else snapshot
        return snapshot

    def _passes_price_common(self, ctx: ScreeningContext) -> bool:
        if not self._common_price:
            return True
        return passes_filters(ctx, self._common_price)

    def _track_passes_without_financials(
        self,
        ctx: ScreeningContext,
        track: TrackEvaluator,
    ) -> bool:
        market_filters, industry_filters, _ = self._track_partitions[track.name]
        if market_filters and not passes_without_financials(ctx, market_filters):
            return False
        if industry_filters and not passes_filters(ctx, industry_filters):
            return False
        return True

    def _needs_financial_fetch(self, ctx: ScreeningContext) -> bool:
        if self._common_financial:
            return True
        for track in self.tracks:
            if not needs_financials(track.filters):
                continue
            if not self._track_passes_without_financials(ctx, track):
                continue
            if not track_soft_passes_market(ctx, track.filters):
                continue
            return True
        return False

    def _match_track(self, ctx: ScreeningContext) -> str | None:
        if not self.tracks:
            if passes_filters(ctx, self.common_filters):
                return "default"
            return None
        if not passes_filters(ctx, self.common_filters):
            return None
        for track in self.tracks:
            if passes_filters(ctx, track.filters):
                return track.name
        return None

    def _candidate_hit(self, ctx: ScreeningContext, track: str, market: Market) -> CandidateHit:
        score, components = compute_score(ctx, self.config.scoring)
        metrics = extract_metrics(ctx, score, components)
        metrics["track"] = track
        return CandidateHit(
            code=ctx.stock.code,
            name=ctx.stock.name,
            market=market,
            track=track,
            score=score,
            metrics=metrics,
        )

    def _screen_market_stage(
        self,
        provider: MarketDataProvider,
        universe: list[StockInfo],
        bulk_snapshots: dict[str, MarketSnapshot],
        industry_returns: dict[str, float],
    ) -> tuple[list[CandidateHit], list[_FinancialCandidate]]:
        immediate_hits: list[CandidateHit] = []
        financial_queue: list[_FinancialCandidate] = []

        for stock in tqdm(universe, desc=f"market-filter-{provider.market.value}"):
            snapshot = self._resolve_snapshot(provider, stock, bulk_snapshots)
            if snapshot is None:
                continue

            ctx = self._build_context(stock, snapshot, industry_returns)
            if self._common_market and not passes_filters(ctx, self._common_market):
                continue

            if self._needs_industry_field and snapshot.industry is None:
                snapshot = provider.enrich_snapshot_industry(snapshot)
                ctx = self._build_context(stock, snapshot, industry_returns)

            if self._common_industry and not passes_filters(ctx, self._common_industry):
                continue

            if self._needs_financial_fetch(ctx):
                financial_queue.append(_FinancialCandidate(stock=stock, snapshot=snapshot))
                continue

            matched_track = self._match_track(ctx)
            if matched_track is not None:
                immediate_hits.append(
                    self._candidate_hit(ctx, matched_track, stock.market)
                )

        return immediate_hits, financial_queue

    def _evaluate_financial_candidate(
        self,
        provider: MarketDataProvider,
        candidate: _FinancialCandidate,
        industry_returns: dict[str, float],
        financials=None,
    ) -> CandidateHit | None:
        if financials is None:
            financials = provider.fetch_financials(candidate.stock.code)
        ctx = self._build_context(
            candidate.stock,
            candidate.snapshot,
            industry_returns,
            financials,
        )
        matched_track = self._match_track(ctx)
        if matched_track is None:
            return None
        return self._candidate_hit(ctx, matched_track, candidate.stock.market)

    def _process_financial_queue(
        self,
        provider: MarketDataProvider,
        financial_queue: list[_FinancialCandidate],
        industry_returns: dict[str, float],
    ) -> list[CandidateHit]:
        if not financial_queue:
            return []

        hits: list[CandidateHit] = []
        workers = max(1, self.config.fetch.financial_workers)
        label = f"financial-{provider.market.value}"

        cached = _fetch_financials_cached(
            provider,
            [candidate.stock.code for candidate in financial_queue],
        )
        pending: list[_FinancialCandidate] = []
        for candidate in financial_queue:
            financials = cached.get(candidate.stock.code)
            if financials is None:
                pending.append(candidate)
                continue
            result = self._evaluate_financial_candidate(
                provider,
                candidate,
                industry_returns,
                financials=financials,
            )
            if result is not None:
                hits.append(result)

        if not pending:
            return hits

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._evaluate_financial_candidate,
                    provider,
                    candidate,
                    industry_returns,
                ): candidate
                for candidate in pending
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc=label):
                result = future.result()
                if result is not None:
                    hits.append(result)
        return hits

    def run(self) -> list[CandidateHit]:
        all_hits: list[CandidateHit] = []
        lookback_years = 3
        for spec in self.config.common_filters:
            if spec.get("type") == "non_declining_industry":
                lookback_years = int(spec.get("lookback_years", 3))
                break

        for market in self.config.markets:
            provider = self.providers[market]
            universe = self.build_universe(market)
            industry_returns = (
                provider.fetch_industry_returns(lookback_years)
                if self._needs_industry_returns
                else {}
            )

            universe_codes = {stock.code for stock in universe}
            bulk_snapshots = _fetch_price_snapshots(
                provider,
                universe_codes,
                include_52w=self._needs_52w,
            )

            # Layer 1 — hard price constraints (ST / 52w / drawdown).
            price_universe: list[StockInfo] = []
            price_snapshots: dict[str, MarketSnapshot] = {}
            for stock in tqdm(universe, desc=f"price-filter-{market.value}"):
                snapshot = self._resolve_snapshot(provider, stock, bulk_snapshots)
                if snapshot is None:
                    continue
                ctx = self._build_context(stock, snapshot, industry_returns)
                if not self._passes_price_common(ctx):
                    continue
                price_universe.append(stock)
                price_snapshots[stock.code] = snapshot

            # Layer 2 — enrich PE/PB/PS/div only for price survivors.
            if self._needs_valuation_enrichment and price_snapshots:
                price_snapshots = _enrich_snapshots(provider, price_snapshots)

            immediate_hits, financial_queue = self._screen_market_stage(
                provider,
                price_universe,
                price_snapshots,
                industry_returns,
            )
            all_hits.extend(immediate_hits)
            all_hits.extend(
                self._process_financial_queue(provider, financial_queue, industry_returns)
            )

        all_hits.sort(key=lambda item: item.score, reverse=True)
        top_n = self.config.output.top_n
        trimmed = all_hits[:top_n] if top_n else all_hits

        if self.state_store is not None:
            trimmed = filter_candidates(
                trimmed,
                self.state_store,
                drop_ratio=self.config.state.too_expensive_drop_ratio,
            )
        return trimmed

    def save(self, hits: list[CandidateHit]) -> tuple[Path, Path, Path]:
        output_dir = Path(self.config.output.directory)
        output_dir.mkdir(parents=True, exist_ok=True)

        json_path = output_dir / self.config.output.candidates_json
        csv_path = output_dir / self.config.output.candidates_csv
        legacy_path = output_dir / self.config.output.filename

        payload = {
            "top_n": self.config.output.top_n,
            "count": len(hits),
            "candidates": [hit.to_dict() for hit in hits],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        fieldnames = [
            "code",
            "name",
            "market",
            "track",
            "score",
            "drawdown_pct",
            "price_to_low_ratio",
            "pe",
            "dividend_yield_pct",
            "industry",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for hit in hits:
                row = hit.to_dict()
                metrics = row.pop("metrics", {})
                row.pop("stock_key", None)
                writer.writerow({**row, **metrics})

        with legacy_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["code", "name", "market", "track", "score"])
            writer.writeheader()
            for hit in hits:
                writer.writerow(
                    {
                        "code": hit.stock_key,
                        "name": hit.name,
                        "market": hit.market.value,
                        "track": hit.track,
                        "score": round(hit.score, 2),
                    }
                )

        return json_path, csv_path, legacy_path


def hits_as_legacy(hits: list[CandidateHit]) -> list[ScreenHit]:
    return [
        ScreenHit(code=hit.code, name=hit.name, market=hit.market)
        for hit in hits
    ]


def normalize_code_manual(code: str) -> str:
    return code.strip().split(".")[0].zfill(6)
