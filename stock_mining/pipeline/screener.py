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
from stock_mining.models import CandidateHit, ScreenHit, ScreeningContext, StockInfo
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.scoring.engine import compute_score, extract_metrics
from stock_mining.state.store import UserStateStore
from stock_mining.utils import is_bj_code, is_st_name, match_industry_return


@dataclass
class TrackEvaluator:
    name: str
    filters: list[Filter]


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
        market_snapshot,
        industry_returns: dict[str, float],
        financials=None,
        matched_track: str | None = None,
    ) -> ScreeningContext:
        industry_return = match_industry_return(
            market_snapshot.industry if market_snapshot else None,
            industry_returns,
        )
        return ScreeningContext(
            stock=StockInfo(
                code=market_snapshot.code,
                name=market_snapshot.name,
                market=stock.market,
            ),
            market=market_snapshot,
            financials=financials,
            industry_return_3y_pct=industry_return,
            matched_track=matched_track,
        )

    def _passes_filters(self, ctx: ScreeningContext, filters: list[Filter]) -> bool:
        return all(filter_.evaluate(ctx).passed for filter_ in filters)

    def _match_track(self, ctx: ScreeningContext) -> str | None:
        if not self.tracks:
            return "default" if self._passes_filters(ctx, self.common_filters) else None
        if not self._passes_filters(ctx, self.common_filters):
            return None
        for track in self.tracks:
            if self._passes_filters(ctx, track.filters):
                return track.name
        return None

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

            candidates = list(universe)

            workers = max(1, self.config.fetch.financial_workers)

            def evaluate_one(stock: StockInfo) -> CandidateHit | None:
                market_snapshot = provider.fetch_stock_snapshot(stock.code, stock.name)
                financials = provider.fetch_financials(stock.code)
                ctx = self._build_context(stock, market_snapshot, industry_returns, financials)
                matched_track = self._match_track(ctx)
                if matched_track is None:
                    return None
                score, components = compute_score(ctx, self.config.scoring)
                metrics = extract_metrics(ctx, score, components)
                metrics["track"] = matched_track
                return CandidateHit(
                    code=ctx.stock.code,
                    name=ctx.stock.name,
                    market=stock.market,
                    track=matched_track,
                    score=score,
                    metrics=metrics,
                )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(evaluate_one, stock): stock for stock in candidates
                }
                label = f"screening-{market.value}"
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
                cooldown_days=self.config.state.recommendation_cooldown_days,
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
