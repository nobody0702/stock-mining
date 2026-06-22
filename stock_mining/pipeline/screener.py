from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from stock_mining.config import PipelineConfig, TrackConfig, load_pipeline_config
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.base import Filter
from stock_mining.filters.registry import build_filters
from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.markets.providers import build_market_providers
from stock_mining.models import CandidateHit, MarketSnapshot, ScreenHit, ScreeningContext, StockInfo
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.pipeline.funnel import (
    needs_financials,
    needs_industry_name,
    partition_filters,
    passes_filters,
    passes_without_financials,
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
        self._track_partitions = {
            track.name: partition_filters(track.filters) for track in self.tracks
        }
        all_filters = self.common_filters + [
            filter_ for track in self.tracks for filter_ in track.filters
        ]
        self._needs_industry_field = needs_industry_name(all_filters)

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        state_store: UserStateStore | None = None,
    ) -> "DailyScreener":
        config = load_pipeline_config(path)
        if state_store is None:
            state_store = UserStateStore(config.state.db_path)
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
            return [
                StockInfo(
                    code=normalize_stock_code(code, market),
                    name=name_map.get(normalize_stock_code(code, market), code),
                    market=market,
                )
                for code in self.config.universe.codes
            ]

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
        if snapshot is not None:
            return snapshot
        if stock.market == Market.HK:
            return provider.fetch_stock_snapshot(stock.code, stock.name)
        return None

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
            if self._track_passes_without_financials(ctx, track):
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
    ) -> CandidateHit | None:
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
            bulk_snapshots = provider.fetch_market_snapshots(universe_codes)
            immediate_hits, financial_queue = self._screen_market_stage(
                provider,
                universe,
                bulk_snapshots,
                industry_returns,
            )
            all_hits.extend(immediate_hits)

            workers = max(1, self.config.fetch.financial_workers)
            label = f"financial-{market.value}"

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self._evaluate_financial_candidate,
                        provider,
                        candidate,
                        industry_returns,
                    ): candidate
                    for candidate in financial_queue
                }
                for future in tqdm(as_completed(futures), total=len(futures), desc=label):
                    result = future.result()
                    if result is not None:
                        all_hits.append(result)

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
                writer.writerow({**row, **metrics})

        with legacy_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["code", "name", "market", "track", "score"])
            writer.writeheader()
            for hit in hits:
                writer.writerow(
                    {
                        "code": hit.code,
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
