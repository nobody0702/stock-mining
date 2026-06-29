from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import akshare as ak
import pandas as pd
from tqdm import tqdm

from stock_mining.data.base import MarketDataProvider
from stock_mining.data.cache import SqliteCache, deserialize_financials, serialize_financials
from stock_mining.data.http_retry import call_with_retry
from stock_mining.markets.base import Market, calc_drawdown_from_high_pct, normalize_stock_code
from stock_mining.markets.hk_indicators import parse_hk_indicator_metrics
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.utils import coalesce_row, parse_money_to_yuan, parse_number, parse_percent, parse_report_date

TRADING_DAYS_52W = 260


class AkshareHkConnectProvider(MarketDataProvider):
    """Hong Kong Stock Connect constituents via AkShare."""

    @property
    def market(self) -> Market:
        return Market.HK

    def __init__(
        self,
        *,
        use_cache: bool = True,
        cache_dir: str = "data/cache",
        cache_ttl_hours: int = 12,
        request_interval_sec: float = 0.15,
        network_retries: int = 5,
        snapshot_workers: int = 4,
    ) -> None:
        self.request_interval_sec = request_interval_sec
        self.network_retries = network_retries
        self.snapshot_workers = max(1, snapshot_workers)
        self._last_request_at = 0.0
        self.cache = (
            SqliteCache(cache_dir, ttl_hours=cache_ttl_hours, namespace_prefix="hk")
            if use_cache
            else None
        )

    def _throttle(self) -> None:
        if self.request_interval_sec <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.request_interval_sec:
            time.sleep(self.request_interval_sec - elapsed)
        self._last_request_at = time.time()

    def list_stocks(self) -> list[StockInfo]:
        cache_key = "ggt_components"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return [
                    StockInfo(code=item["code"], name=item["name"], market=Market.HK)
                    for item in cached
                ]

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_hk_ggt_components_em()

        df = call_with_retry(_fetch, retries=self.network_retries)
        stocks = [
            StockInfo(
                code=normalize_stock_code(str(row["代码"]), Market.HK),
                name=str(row["名称"]).strip(),
                market=Market.HK,
            )
            for _, row in df.iterrows()
        ]
        if self.cache is not None:
            self.cache.set(
                "market",
                cache_key,
                [{"code": s.code, "name": s.name} for s in stocks],
            )
        return stocks

    def fetch_dividend_map(self) -> dict[str, float]:
        return {}

    def fetch_market_snapshots(
        self,
        codes: set[str] | None = None,
    ) -> dict[str, MarketSnapshot]:
        stocks = self.list_stocks()
        if codes is not None:
            stocks = [stock for stock in stocks if stock.code in codes]
        stubs = {
            stock.code: MarketSnapshot(code=stock.code, name=stock.name, market=Market.HK)
            for stock in stocks
        }
        return self.enrich_snapshots(stubs)

    def enrich_snapshots(
        self,
        snapshots: dict[str, MarketSnapshot],
    ) -> dict[str, MarketSnapshot]:
        if not snapshots:
            return {}
        workers = min(self.snapshot_workers, len(snapshots))
        enriched: dict[str, MarketSnapshot] = {}

        def _enrich_one(code: str, stub: MarketSnapshot) -> MarketSnapshot:
            return self.fetch_stock_snapshot(
                code,
                stub.name,
                include_dividend=True,
                fast=False,
            )

        if workers <= 1:
            for code, stub in snapshots.items():
                enriched[code] = _enrich_one(code, stub)
            return enriched

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_enrich_one, code, stub): code
                for code, stub in snapshots.items()
            }
            for future in tqdm(as_completed(futures), total=len(futures), desc="hk-snapshot"):
                code = futures[future]
                enriched[code] = future.result()
        return enriched

    def fetch_stock_snapshot(
        self,
        code: str,
        name: str,
        *,
        include_dividend: bool = True,
        fast: bool = False,
    ) -> MarketSnapshot:
        code = normalize_stock_code(code, Market.HK)
        cache_key = f"snapshot_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                payload = dict(cached)
                if name:
                    payload["name"] = name
                return MarketSnapshot(**payload)

        valuation = self._fetch_valuation(code)
        indicators = self._fetch_indicator_metrics(code)
        resolved_name = name or code
        industry = self._fetch_industry(code)
        snapshot = MarketSnapshot(
            code=code,
            name=resolved_name,
            market=Market.HK,
            industry=industry,
            price=valuation.get("price"),
            low_52w=valuation.get("low_52w"),
            high_52w=valuation.get("high_52w"),
            drawdown_from_high_pct=valuation.get("drawdown_from_high_pct"),
            pe=indicators.get("pe"),
            pb=indicators.get("pb"),
            ps=indicators.get("ps"),
            dividend_yield_pct=indicators.get("dividend_yield_pct")
            if include_dividend
            else None,
            market_cap_yuan=indicators.get("market_cap_yuan"),
        )
        if self.cache is not None:
            self.cache.set("market", cache_key, snapshot.__dict__)
        return snapshot

    def enrich_snapshot_industry(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        if snapshot.industry is not None:
            return snapshot
        industry = self._fetch_industry(snapshot.code)
        return MarketSnapshot(
            code=snapshot.code,
            name=snapshot.name,
            market=snapshot.market,
            industry=industry,
            price=snapshot.price,
            low_52w=snapshot.low_52w,
            high_52w=snapshot.high_52w,
            drawdown_from_high_pct=snapshot.drawdown_from_high_pct,
            pe=snapshot.pe,
            pb=snapshot.pb,
            ps=snapshot.ps,
            dividend_yield_pct=snapshot.dividend_yield_pct,
            market_cap_yuan=snapshot.market_cap_yuan,
        )

    def _fetch_industry(self, code: str) -> str | None:
        return None

    def _fetch_indicator_metrics(self, code: str) -> dict[str, float | None]:
        cache_key = f"indicator_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return dict(cached)

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_hk_financial_indicator_em(symbol=code)

        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            return {}

        if df is None or df.empty:
            return {}

        metrics = parse_hk_indicator_metrics(df.iloc[0])
        if self.cache is not None:
            self.cache.set("market", cache_key, metrics)
        return metrics

    def _fetch_valuation(self, code: str) -> dict[str, float | None]:
        self._throttle()
        end = date.today()
        start = end - timedelta(days=400)

        def _fetch() -> pd.DataFrame:
            return ak.stock_hk_daily(symbol=code, adjust="qfq")

        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            return _empty_valuation()

        if df is None or df.empty:
            return _empty_valuation()

        recent = df.tail(TRADING_DAYS_52W)
        latest = df.iloc[-1]
        close_col = "close" if "close" in df.columns else "收盘"
        low_52w = float(recent[close_col].min()) if not recent.empty else None
        high_52w = float(recent[close_col].max()) if not recent.empty else None
        price = _safe_float(latest.get(close_col))
        return {
            "price": price,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "drawdown_from_high_pct": calc_drawdown_from_high_pct(price, high_52w),
        }

    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        return {}

    def fetch_financials(self, code: str, *, fast: bool = False) -> StockFinancials:
        code = normalize_stock_code(code, Market.HK)
        if self.cache is not None:
            cached = self.cache.get("financial", code)
            if cached is not None:
                return deserialize_financials(cached)

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_financial_hk_analysis_indicator_em(symbol=code, indicator="年度")

        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            df = pd.DataFrame()

        financials = self._parse_financials(code, df)
        if self.cache is not None:
            self.cache.set("financial", code, serialize_financials(financials))
        return financials

    @staticmethod
    def _parse_financials(code: str, df: pd.DataFrame) -> StockFinancials:
        if df is None or df.empty:
            return StockFinancials(code=code, market=Market.HK, annual=[])

        annual: list[AnnualMetrics] = []
        for _, row in df.iterrows():
            report_date = parse_report_date(coalesce_row(row, "报告期", "REPORT_DATE"))
            if report_date is None:
                continue
            annual.append(
                AnnualMetrics(
                    report_date=report_date,
                    net_profit_yuan=parse_money_to_yuan(
                        coalesce_row(row, "净利润", "HOLDER_PROFIT")
                    ),
                    revenue_yuan=parse_money_to_yuan(
                        coalesce_row(row, "营业收入", "OPERATE_INCOME")
                    ),
                    gross_margin_pct=parse_percent(
                        coalesce_row(row, "销售毛利率", "GROSS_PROFIT_RATIO")
                    ),
                    net_margin_pct=parse_percent(
                        coalesce_row(row, "销售净利率", "NET_PROFIT_RATIO")
                    ),
                    operating_cashflow_yuan=parse_money_to_yuan(
                        coalesce_row(row, "经营现金流量净额", "NETCASH_OPERATE")
                    ),
                    debt_ratio_pct=parse_percent(
                        coalesce_row(row, "资产负债率", "DEBT_ASSET_RATIO")
                    ),
                    roe_pct=parse_percent(coalesce_row(row, "净资产收益率", "ROE")),
                )
            )
        annual.sort(key=lambda item: item.report_date)
        return StockFinancials(code=code, market=Market.HK, annual=annual)


def _empty_valuation() -> dict[str, float | None]:
    return {
        "price": None,
        "low_52w": None,
        "high_52w": None,
        "drawdown_from_high_pct": None,
    }


def _safe_float(value: object) -> float | None:
    return parse_number(value)
