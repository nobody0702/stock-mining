from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

from stock_mining.config import PipelineConfig, load_pipeline_config
from stock_mining.data.akshare_provider import build_data_provider
from stock_mining.data.base import MarketDataProvider
from stock_mining.filters.base import Filter
from stock_mining.filters.registry import build_filters
from stock_mining.models import ScreenHit, ScreeningContext, StockInfo
from stock_mining.utils import is_bj_code, is_st_name, match_industry_return


class DailyScreener:
    def __init__(
        self,
        config: PipelineConfig,
        provider: MarketDataProvider,
        filters: list[Filter],
    ) -> None:
        self.config = config
        self.provider = provider
        self.filters = filters
        self._needs_industry_returns = any(
            f.requires_industry_returns for f in filters
        )
        self._dividend_threshold = _dividend_threshold_from_filters(filters)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DailyScreener":
        config = load_pipeline_config(path)
        provider = build_data_provider(
            config.data_source,
            use_cache=config.fetch.use_cache,
            cache_dir=config.fetch.cache_dir,
            cache_ttl_hours=config.fetch.cache_ttl_hours,
            request_interval_sec=config.fetch.request_interval_sec,
        )
        filters = build_filters(config.filters)
        return cls(config, provider, filters)

    def build_universe(self) -> list[StockInfo]:
        if self.config.universe.codes:
            name_map = {item.code: item.name for item in self.provider.list_stocks()}
            return [
                StockInfo(
                    code=normalize_code_manual(code),
                    name=name_map.get(normalize_code_manual(code), code),
                )
                for code in self.config.universe.codes
            ]

        stocks = self.provider.list_stocks()
        filtered: list[StockInfo] = []
        for stock in stocks:
            if self.config.universe.exclude_st and is_st_name(stock.name):
                continue
            if self.config.universe.exclude_bj and is_bj_code(stock.code):
                continue
            filtered.append(stock)

        max_stocks = self.config.universe.max_stocks
        if max_stocks is not None:
            filtered = filtered[: int(max_stocks)]
        return filtered

    def _build_context(
        self,
        stock: StockInfo,
        market,
        industry_returns: dict[str, float],
        financials=None,
    ) -> ScreeningContext:
        industry_return = match_industry_return(
            market.industry if market else None, industry_returns
        )
        return ScreeningContext(
            stock=StockInfo(code=market.code, name=market.name),
            market=market,
            financials=financials,
            industry_return_3y_pct=industry_return,
        )

    def _passes_all_filters(self, ctx: ScreeningContext) -> bool:
        return all(filter_.evaluate(ctx).passed for filter_ in self.filters)

    def run(self) -> list[ScreenHit]:
        universe = self.build_universe()
        dividend_map = self.provider.fetch_dividend_map()

        lookback_years = 3
        for spec in self.config.filters:
            if spec.get("type") == "non_declining_industry":
                lookback_years = int(spec.get("lookback_years", 3))
                break
        industry_returns = (
            self.provider.fetch_industry_returns(lookback_years)
            if self._needs_industry_returns
            else {}
        )

        candidates: list[StockInfo] = []
        for stock in universe:
            if self._dividend_threshold is not None:
                dividend = dividend_map.get(stock.code)
                if dividend is None or dividend <= self._dividend_threshold:
                    continue
            candidates.append(stock)

        hits: list[ScreenHit] = []
        workers = max(1, self.config.fetch.financial_workers)

        def evaluate_one(stock: StockInfo) -> ScreenHit | None:
            market = self.provider.fetch_stock_snapshot(stock.code, stock.name)
            financials = self.provider.fetch_financials(stock.code)
            ctx = self._build_context(stock, market, industry_returns, financials)
            if self._passes_all_filters(ctx):
                return ScreenHit(code=ctx.stock.code, name=ctx.stock.name)
            return None

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(evaluate_one, stock): stock for stock in candidates
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="screening"):
                result = future.result()
                if result is not None:
                    hits.append(result)

        hits.sort(key=lambda item: item.code)
        return hits

    def save(self, hits: list[ScreenHit]) -> Path:
        output_dir = Path(self.config.output.directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / self.config.output.filename
        with output_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=["code", "name"])
            writer.writeheader()
            for hit in hits:
                writer.writerow({"code": hit.code, "name": hit.name})
        return output_path


def _dividend_threshold_from_filters(filters: list[Filter]) -> float | None:
    for filter_ in filters:
        threshold = getattr(filter_, "threshold_pct", None)
        if threshold is not None and filter_.name == "dividend_yield":
            return float(threshold)
        if threshold is not None and type(filter_).__name__ == "DividendYieldMinFilter":
            return float(threshold)
    return None


def normalize_code_manual(code: str) -> str:
    return code.strip().split(".")[0].zfill(6)
