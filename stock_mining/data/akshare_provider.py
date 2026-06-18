from __future__ import annotations

import time
from datetime import date, timedelta

import akshare as ak
import pandas as pd

from stock_mining.data.base import MarketDataProvider
from stock_mining.data.cache import SqliteCache, deserialize_financials, serialize_financials
from stock_mining.data.http_retry import call_with_retry
from stock_mining.markets.base import Market, calc_drawdown_from_high_pct
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.utils import (
    normalize_code,
    parse_money_to_yuan,
    parse_number,
    parse_percent,
    parse_report_date,
)

FHPS_REPORT_DATES = ("20251231", "20250630", "20241231", "20240630")
TRADING_DAYS_52W = 260


class AkshareDataProvider(MarketDataProvider):
    """AkShare provider with multi-source fallbacks (East Money bulk APIs may fail)."""

    @property
    def market(self) -> Market:
        return Market.A

    def __init__(
        self,
        *,
        use_cache: bool = True,
        cache_dir: str = "data/cache",
        cache_ttl_hours: int = 12,
        request_interval_sec: float = 0.15,
        network_retries: int = 5,
    ) -> None:
        self.request_interval_sec = request_interval_sec
        self.network_retries = network_retries
        self._last_request_at = 0.0
        self.cache = (
            SqliteCache(cache_dir, ttl_hours=cache_ttl_hours) if use_cache else None
        )
        self._dividend_map: dict[str, float] | None = None

    def _throttle(self) -> None:
        if self.request_interval_sec <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if elapsed < self.request_interval_sec:
            time.sleep(self.request_interval_sec - elapsed)
        self._last_request_at = time.time()

    def list_stocks(self) -> list[StockInfo]:
        df = call_with_retry(
            ak.stock_info_a_code_name,
            retries=self.network_retries,
        )
        return [
            StockInfo(code=normalize_code(str(row["code"])), name=str(row["name"]).strip(), market=Market.A)
            for _, row in df.iterrows()
        ]

    def fetch_dividend_map(self) -> dict[str, float]:
        if self._dividend_map is not None:
            return self._dividend_map

        cache_key = "dividend_map"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                self._dividend_map = {k: float(v) for k, v in cached.items()}
                return self._dividend_map

        last_error: Exception | None = None
        for report_date in FHPS_REPORT_DATES:
            try:
                self._throttle()

                def _fetch(date_str: str = report_date) -> pd.DataFrame:
                    return ak.stock_fhps_em(date=date_str)

                df = call_with_retry(_fetch, retries=self.network_retries)
                mapping = _parse_dividend_dataframe(df)
                if mapping:
                    self._dividend_map = mapping
                    if self.cache is not None:
                        self.cache.set("market", cache_key, mapping)
                    return mapping
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if self.cache is not None:
            stale = self.cache.get_allow_stale("market", cache_key)
            if stale is not None:
                self._dividend_map = {k: float(v) for k, v in stale.items()}
                return self._dividend_map

        if last_error is not None:
            raise last_error
        return {}

    def fetch_market_snapshots(self) -> dict[str, MarketSnapshot]:
        """Build partial snapshots; call fetch_stock_snapshot() for full enrichment."""
        dividend_map = self.fetch_dividend_map()
        stocks = self.list_stocks()
        snapshots: dict[str, MarketSnapshot] = {}
        for stock in stocks:
            snapshots[stock.code] = MarketSnapshot(
                code=stock.code,
                name=stock.name,
                dividend_yield_pct=dividend_map.get(stock.code),
            )
        return snapshots

    def fetch_stock_snapshot(self, code: str, name: str) -> MarketSnapshot:
        code = normalize_code(code)
        cache_key = f"snapshot_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return MarketSnapshot(**cached)

        dividend_map = self.fetch_dividend_map()
        industry = self._fetch_industry(code)
        valuation = self._fetch_valuation(code)

        snapshot = MarketSnapshot(
            code=code,
            name=name,
            market=Market.A,
            industry=industry,
            price=valuation.get("price"),
            low_52w=valuation.get("low_52w"),
            high_52w=valuation.get("high_52w"),
            drawdown_from_high_pct=valuation.get("drawdown_from_high_pct"),
            pe=valuation.get("pe"),
            pb=valuation.get("pb"),
            ps=valuation.get("ps"),
            dividend_yield_pct=dividend_map.get(code),
        )
        if self.cache is not None:
            self.cache.set("market", cache_key, snapshot.__dict__)
        return snapshot

    def _fetch_industry(self, code: str) -> str | None:
        cache_key = f"industry_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return cached or None

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_profile_cninfo(symbol=code)

        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
            if df is None or df.empty or "所属行业" not in df.columns:
                industry = None
            else:
                industry = str(df.iloc[0]["所属行业"]).strip() or None
        except Exception:
            industry = None

        if self.cache is not None:
            self.cache.set("market", cache_key, industry or "")
        return industry

    def _fetch_valuation(self, code: str) -> dict[str, float | None]:
        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_value_em(symbol=code)

        df = call_with_retry(_fetch, retries=self.network_retries)
        if df is None or df.empty:
            return {
                "price": None,
                "low_52w": None,
                "pe": None,
                "pb": None,
                "ps": None,
            }

        recent = df.tail(TRADING_DAYS_52W)
        latest = df.iloc[-1]
        low_52w = float(recent["当日收盘价"].min()) if not recent.empty else None
        high_52w = float(recent["当日收盘价"].max()) if not recent.empty else None
        price = _safe_float(latest.get("当日收盘价"))
        return {
            "price": price,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "drawdown_from_high_pct": calc_drawdown_from_high_pct(price, high_52w),
            "pe": _safe_float(latest.get("PE(TTM)")),
            "pb": _safe_float(latest.get("市净率")),
            "ps": _safe_float(latest.get("市销率")),
        }

    def fetch_industry_returns(self, lookback_years: int) -> dict[str, float]:
        cache_key = f"industry_returns_{lookback_years}y"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return {k: float(v) for k, v in cached.items()}

        end = date.today()
        start = end - timedelta(days=365 * lookback_years + 30)
        start_s = start.strftime("%Y%m%d")
        end_s = end.strftime("%Y%m%d")

        try:
            self._throttle()

            def _fetch_boards() -> pd.DataFrame:
                return ak.stock_board_industry_name_em()

            boards = call_with_retry(_fetch_boards, retries=3)
        except Exception:
            if self.cache is not None:
                stale = self.cache.get_allow_stale("market", cache_key)
                if stale is not None:
                    return {k: float(v) for k, v in stale.items()}
            return {}

        returns: dict[str, float] = {}
        for _, row in boards.iterrows():
            industry = str(row["板块名称"]).strip()
            try:
                self._throttle()

                def _fetch_hist(ind: str = industry) -> pd.DataFrame:
                    return ak.stock_board_industry_hist_em(
                        symbol=ind,
                        start_date=start_s,
                        end_date=end_s,
                        period="日k",
                        adjust="",
                    )

                hist = call_with_retry(_fetch_hist, retries=2)
                if hist is None or hist.empty or len(hist) < 2:
                    continue
                first_close = float(hist.iloc[0]["收盘"])
                last_close = float(hist.iloc[-1]["收盘"])
                if first_close <= 0:
                    continue
                returns[industry] = (last_close / first_close - 1.0) * 100.0
            except Exception:
                continue

        if self.cache is not None and returns:
            self.cache.set("market", cache_key, returns)
        return returns

    def fetch_financials(self, code: str) -> StockFinancials:
        code = normalize_code(code)
        if self.cache is not None:
            cached = self.cache.get("financial", code)
            if cached is not None:
                return deserialize_financials(cached)

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_financial_abstract_ths(symbol=code)

        df = call_with_retry(_fetch, retries=self.network_retries)
        financials = self._parse_financials(code, df)
        if self.cache is not None:
            self.cache.set("financial", code, serialize_financials(financials))
        return financials

    @staticmethod
    def _parse_financials(code: str, df: pd.DataFrame) -> StockFinancials:
        if df is None or df.empty:
            return StockFinancials(code=code, annual=[])

        annual: list[AnnualMetrics] = []
        for _, row in df.iterrows():
            report_date = parse_report_date(row.get("报告期"))
            if report_date is None or report_date > date.today():
                continue
            annual.append(
                AnnualMetrics(
                    report_date=report_date,
                    net_profit_yuan=parse_money_to_yuan(row.get("净利润")),
                    revenue_yuan=parse_money_to_yuan(
                        row.get("营业总收入") or row.get("营业收入")
                    ),
                    gross_margin_pct=parse_percent(row.get("销售毛利率")),
                    net_margin_pct=parse_percent(row.get("销售净利率")),
                    operating_cashflow_per_share=parse_number(row.get("每股经营现金流")),
                    operating_cashflow_yuan=parse_money_to_yuan(row.get("经营现金流量净额")),
                    debt_ratio_pct=parse_percent(row.get("资产负债率")),
                    roe_pct=parse_percent(row.get("净资产收益率")),
                )
            )
        annual.sort(key=lambda item: item.report_date)
        return StockFinancials(code=code, market=Market.A, annual=annual)


def _parse_dividend_dataframe(df: pd.DataFrame) -> dict[str, float]:
    mapping: dict[str, float] = {}
    if df is None or df.empty:
        return mapping
    yield_col = "现金分红-股息率"
    if yield_col not in df.columns:
        return mapping
    for _, row in df.iterrows():
        code = normalize_code(str(row["代码"]))
        parsed = _normalize_dividend_yield(row.get(yield_col))
        if parsed is not None:
            mapping[code] = parsed
    return mapping


def _normalize_dividend_yield(value: object) -> float | None:
    raw = parse_number(value)
    if raw is None:
        return None
    if raw <= 1:
        return raw * 100.0
    return raw


def _safe_float(value: object) -> float | None:
    parsed = parse_number(value)
    return parsed


def build_data_provider(name: str, **kwargs: object) -> MarketDataProvider:
    if name == "akshare":
        return AkshareDataProvider(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported data source: {name}")
