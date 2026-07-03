from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, timedelta

import akshare as ak
import pandas as pd
from tqdm import tqdm

from stock_mining.data.base import MarketDataProvider
from stock_mining.data.cache import SqliteCache, deserialize_financials, serialize_financials
from stock_mining.data.http_retry import call_with_retry, call_with_timeout
from stock_mining.markets.base import Market, calc_drawdown_from_high_pct
from stock_mining.markets.pe_metrics import (
    merge_pe_fields,
    parse_pe_from_spot_row,
    parse_pe_from_value_em_row,
    replace_market_snapshot,
)
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials, StockInfo
from stock_mining.utils import (
    coalesce_row,
    normalize_code,
    parse_money_to_yuan,
    parse_number,
    parse_percent,
    parse_report_date,
)

FHPS_REPORT_DATES = ("20251231", "20250630", "20241231", "20240630")
TRADING_DAYS_52W = 260
HIST_LOOKBACK_DAYS = 400
FAST_REQUEST_TIMEOUT_SEC = 15.0
FAST_REQUEST_RETRIES = 1


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
        snapshot_workers: int = 8,
    ) -> None:
        self.request_interval_sec = request_interval_sec
        self.network_retries = network_retries
        self.snapshot_workers = max(1, snapshot_workers)
        self._last_request_at = 0.0
        self.cache = (
            SqliteCache(cache_dir, ttl_hours=cache_ttl_hours) if use_cache else None
        )
        self._dividend_map: dict[str, float] | None = None
        self._bulk_snapshots: dict[str, MarketSnapshot] | None = None
        self._snapshot_payloads: dict[str, dict] | None = None

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

    def fetch_market_snapshots(
        self,
        codes: set[str] | None = None,
    ) -> dict[str, MarketSnapshot]:
        """Bulk spot + parallel 52-week stats for the A-share universe."""
        if self._bulk_snapshots is not None and codes is None:
            return self._bulk_snapshots

        dividend_map = self.fetch_dividend_map()
        spot_df = self._fetch_bulk_spot()
        snapshots: dict[str, MarketSnapshot] = {}
        for _, row in spot_df.iterrows():
            code = normalize_code(str(row["代码"]))
            if codes is not None and code not in codes:
                continue
            pe_fields = parse_pe_from_spot_row(row)
            snapshots[code] = MarketSnapshot(
                code=code,
                name=str(row["名称"]).strip(),
                market=Market.A,
                price=_safe_float(row.get("最新价")),
                pe=pe_fields["pe"],
                pe_dynamic=pe_fields["pe_dynamic"],
                pb=_safe_float(row.get("市净率")),
                market_cap_yuan=_parse_market_cap_yuan(row.get("总市值")),
                dividend_yield_pct=dividend_map.get(code),
            )

        self._enrich_52w_parallel(snapshots)
        self._merge_cached_snapshot_fields(snapshots)
        if codes is None:
            self._bulk_snapshots = snapshots
        return snapshots

    def _merge_cached_snapshot_fields(self, snapshots: dict[str, MarketSnapshot]) -> None:
        payloads = self._ensure_snapshot_payloads()
        for code, snapshot in snapshots.items():
            payload = payloads.get(code)
            if payload is None:
                continue
            pe_merge = merge_pe_fields(
                pe_ttm=snapshot.pe_ttm
                if snapshot.pe_ttm is not None
                else _safe_float(payload.get("pe_ttm")),
                pe_static=snapshot.pe_static
                if snapshot.pe_static is not None
                else _safe_float(payload.get("pe_static")),
                pe_dynamic=snapshot.pe_dynamic
                if snapshot.pe_dynamic is not None
                else _safe_float(payload.get("pe_dynamic")),
                fallback_pe=snapshot.pe if snapshot.pe is not None else _safe_float(payload.get("pe")),
            )
            snapshots[code] = MarketSnapshot(
                code=snapshot.code,
                name=snapshot.name,
                market=snapshot.market,
                industry=snapshot.industry or (payload.get("industry") or None),
                price=snapshot.price if snapshot.price is not None else _safe_float(payload.get("price")),
                low_52w=snapshot.low_52w if snapshot.low_52w is not None else _safe_float(payload.get("low_52w")),
                high_52w=snapshot.high_52w if snapshot.high_52w is not None else _safe_float(payload.get("high_52w")),
                drawdown_from_high_pct=snapshot.drawdown_from_high_pct
                if snapshot.drawdown_from_high_pct is not None
                else _safe_float(payload.get("drawdown_from_high_pct")),
                pe=pe_merge["pe"],
                pe_ttm=pe_merge["pe_ttm"],
                pe_static=pe_merge["pe_static"],
                pe_dynamic=pe_merge["pe_dynamic"],
                pb=snapshot.pb if snapshot.pb is not None else _safe_float(payload.get("pb")),
                ps=snapshot.ps if snapshot.ps is not None else _safe_float(payload.get("ps")),
                dividend_yield_pct=(
                    snapshot.dividend_yield_pct
                    if snapshot.dividend_yield_pct is not None
                    else _safe_float(payload.get("dividend_yield_pct"))
                ),
                market_cap_yuan=(
                    snapshot.market_cap_yuan
                    if snapshot.market_cap_yuan is not None
                    else _parse_market_cap_yuan(payload.get("market_cap_yuan"))
                ),
            )

    def enrich_snapshot_industry(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        if snapshot.industry is not None:
            return snapshot
        industry = self._fetch_industry(snapshot.code)
        return replace_market_snapshot(snapshot, industry=industry)

    def _fetch_bulk_spot(self) -> pd.DataFrame:
        cache_key = "bulk_spot_em"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return pd.DataFrame(cached)

        last_error: Exception | None = None
        for source in ("eastmoney", "sina"):
            try:
                self._throttle()
                if source == "eastmoney":
                    df = call_with_retry(
                        ak.stock_zh_a_spot_em,
                        retries=self.network_retries,
                    )
                else:
                    df = call_with_retry(
                        ak.stock_zh_a_spot,
                        retries=max(2, self.network_retries // 2),
                    )
                    df = _normalize_sina_spot_df(df)
                if self.cache is not None:
                    self.cache.set("market", cache_key, df.to_dict(orient="records"))
                return df
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if self.cache is not None:
            stale = self.cache.get_allow_stale("market", cache_key)
            if stale is not None:
                return pd.DataFrame(stale)

        if last_error is not None:
            raise last_error
        raise RuntimeError("无法获取 A 股 bulk spot 数据")

    def _ensure_snapshot_payloads(self) -> dict[str, dict]:
        if self._snapshot_payloads is not None:
            return self._snapshot_payloads
        payloads: dict[str, dict] = {}
        if self.cache is not None:
            import json
            import sqlite3

            namespace = self.cache._ns("market")
            with sqlite3.connect(self.cache.db_path) as conn:
                rows = conn.execute(
                    "SELECT key, payload FROM kv_cache WHERE namespace=? AND key LIKE 'snapshot_%'",
                    (namespace,),
                ).fetchall()
            for key, raw in rows:
                code = str(key).removeprefix("snapshot_")
                payloads[code] = json.loads(raw)
        self._snapshot_payloads = payloads
        return payloads

    def _load_cached_52w(self, code: str) -> dict[str, float | None] | None:
        payloads = self._ensure_snapshot_payloads()
        payload = payloads.get(code)
        if payload is not None:
            low = _safe_float(payload.get("low_52w"))
            high = _safe_float(payload.get("high_52w"))
            if low is not None and high is not None:
                return {"low_52w": low, "high_52w": high}

        if self.cache is None:
            return None
        cache_key = f"week52_{code}"
        cached = self.cache.get("market", cache_key) or self.cache.get_allow_stale(
            "market", cache_key
        )
        if cached is None:
            return None
        low = _safe_float(cached.get("low_52w"))
        high = _safe_float(cached.get("high_52w"))
        if low is None or high is None:
            return None
        return {"low_52w": low, "high_52w": high}

    def _enrich_52w_parallel(self, snapshots: dict[str, MarketSnapshot]) -> None:
        pending: list[str] = []
        for code, snapshot in snapshots.items():
            cached = self._load_cached_52w(code)
            if cached is not None:
                high_52w = cached.get("high_52w")
                snapshots[code] = replace_market_snapshot(
                    snapshot,
                    low_52w=cached.get("low_52w"),
                    high_52w=high_52w,
                    drawdown_from_high_pct=calc_drawdown_from_high_pct(
                        snapshot.price, high_52w
                    ),
                )
                continue
            if snapshot.low_52w is None or snapshot.high_52w is None:
                pending.append(code)

        if not pending:
            return

        workers = min(self.snapshot_workers, len(pending))

        def enrich(code: str) -> tuple[str, dict[str, float | None]]:
            return code, self._fetch_52w_from_hist(code)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(enrich, code): code for code in pending}
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc="52w-enrich",
                leave=False,
            ):
                code, stats = future.result()
                snapshot = snapshots[code]
                price = snapshot.price
                high_52w = stats.get("high_52w")
                snapshots[code] = replace_market_snapshot(
                    snapshot,
                    price=price,
                    low_52w=stats.get("low_52w"),
                    high_52w=high_52w,
                    drawdown_from_high_pct=calc_drawdown_from_high_pct(price, high_52w),
                )

    def _fetch_52w_from_hist(self, code: str) -> dict[str, float | None]:
        cached = self._load_cached_52w(code)
        if cached is not None:
            return cached

        cache_key = f"week52_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return {k: _safe_float(v) for k, v in cached.items()}

        self._throttle()
        start = (date.today() - timedelta(days=HIST_LOOKBACK_DAYS)).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")

        def _fetch() -> pd.DataFrame:
            return ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq",
            )

        empty = {"low_52w": None, "high_52w": None}
        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            return empty

        if df is None or df.empty:
            return empty

        close_col = "收盘" if "收盘" in df.columns else "close"
        recent = df.tail(TRADING_DAYS_52W)
        if recent.empty:
            return empty

        low_52w = float(recent[close_col].min())
        high_52w = float(recent[close_col].max())
        result = {"low_52w": low_52w, "high_52w": high_52w}
        if self.cache is not None:
            self.cache.set("market", cache_key, result)
        return result

    def fetch_stock_snapshot(
        self,
        code: str,
        name: str,
        *,
        include_dividend: bool = True,
        fast: bool = False,
    ) -> MarketSnapshot:
        code = normalize_code(code)
        if self._bulk_snapshots is not None and code in self._bulk_snapshots:
            snapshot = self._bulk_snapshots[code]
            if snapshot.industry is None:
                return self.enrich_snapshot_industry(snapshot)
            return snapshot

        cache_key = f"snapshot_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                payload = dict(cached)
                if name:
                    payload["name"] = name
                return MarketSnapshot(**payload)

        if fast:
            valuation = self._fetch_valuation_fast(code)
            resolved_name = name
            industry = None
            dividend_yield_pct = None
        else:
            dividend_yield_pct = None
            if include_dividend:
                dividend_map = self.fetch_dividend_map()
                dividend_yield_pct = dividend_map.get(code)
            industry = self._fetch_industry(code)
            valuation = self._fetch_valuation(code)
            resolved_name = name

        snapshot = MarketSnapshot(
            code=code,
            name=resolved_name,
            market=Market.A,
            industry=industry,
            price=valuation.get("price"),
            low_52w=valuation.get("low_52w"),
            high_52w=valuation.get("high_52w"),
            drawdown_from_high_pct=valuation.get("drawdown_from_high_pct"),
            pe=valuation.get("pe"),
            pe_ttm=valuation.get("pe_ttm"),
            pe_static=valuation.get("pe_static"),
            pe_dynamic=valuation.get("pe_dynamic"),
            pb=valuation.get("pb"),
            ps=valuation.get("ps"),
            market_cap_yuan=valuation.get("market_cap_yuan"),
            dividend_yield_pct=dividend_yield_pct,
        )
        if self.cache is not None:
            self.cache.set("market", cache_key, snapshot.__dict__)
        return snapshot

    def _fetch_cninfo_profile(
        self,
        code: str,
        *,
        fast: bool = False,
    ) -> dict[str, str | None]:
        cache_key = f"profile_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return {
                    "name": cached.get("name") or None,
                    "industry": cached.get("industry") or None,
                }

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_profile_cninfo(symbol=code)

        retries = FAST_REQUEST_RETRIES if fast else self.network_retries
        try:
            if fast:
                df = call_with_timeout(
                    lambda: call_with_retry(_fetch, retries=retries),
                    timeout_sec=FAST_REQUEST_TIMEOUT_SEC,
                    retries=retries,
                )
            else:
                df = call_with_retry(_fetch, retries=retries)
        except Exception:
            return {"name": None, "industry": None}

        name: str | None = None
        industry: str | None = None
        if df is not None and not df.empty:
            row = df.iloc[0]
            if "证券简称" in df.columns:
                name = str(row.get("证券简称")).strip() or None
            if "所属行业" in df.columns:
                industry = str(row.get("所属行业")).strip() or None

        payload = {"name": name or "", "industry": industry or ""}
        if self.cache is not None:
            self.cache.set("market", cache_key, payload)
        return {"name": name, "industry": industry}

    def _fetch_valuation_fast(self, code: str) -> dict[str, float | None]:
        cache_key = f"valuation_fast_{code}"
        if self.cache is not None:
            cached = self.cache.get("market", cache_key)
            if cached is not None:
                return {k: _safe_float(v) for k, v in cached.items()}

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_value_em(symbol=code)

        empty = {
            "price": None,
            "low_52w": None,
            "high_52w": None,
            "drawdown_from_high_pct": None,
            "pe": None,
            "pe_ttm": None,
            "pe_static": None,
            "pe_dynamic": None,
            "pb": None,
            "ps": None,
            "market_cap_yuan": None,
        }
        try:
            df = call_with_timeout(
                _fetch,
                timeout_sec=FAST_REQUEST_TIMEOUT_SEC,
                retries=FAST_REQUEST_RETRIES,
            )
        except Exception:
            return empty

        if df is None or df.empty:
            return empty

        latest = df.iloc[-1]
        price = _safe_float(latest.get("当日收盘价"))
        pe_breakdown = parse_pe_from_value_em_row(latest)
        pe_fields = merge_pe_fields(
            pe_ttm=pe_breakdown["pe_ttm"],
            pe_static=pe_breakdown["pe_static"],
        )
        result = {
            "price": price,
            "low_52w": None,
            "high_52w": None,
            "drawdown_from_high_pct": None,
            **pe_fields,
            "pb": _safe_float(latest.get("市净率")),
            "ps": _safe_float(latest.get("市销率")),
            "market_cap_yuan": _parse_market_cap_yuan(
                coalesce_row(latest, "总市值", "市值")
            ),
        }
        if self.cache is not None:
            self.cache.set("market", cache_key, result)
        return result

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
        stats = self._fetch_52w_from_hist(code)
        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_value_em(symbol=code)

        try:
            df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            df = None

        pe = pb = ps = price = market_cap_yuan = None
        pe_ttm = pe_static = pe_dynamic = None
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            price = _safe_float(latest.get("当日收盘价"))
            pe_breakdown = parse_pe_from_value_em_row(latest)
            pe_ttm = pe_breakdown["pe_ttm"]
            pe_static = pe_breakdown["pe_static"]
            pe_fields = merge_pe_fields(pe_ttm=pe_ttm, pe_static=pe_static)
            pe = pe_fields["pe"]
            pb = _safe_float(latest.get("市净率"))
            ps = _safe_float(latest.get("市销率"))
            market_cap_yuan = _parse_market_cap_yuan(
                coalesce_row(latest, "总市值", "市值")
            )

        low_52w = stats.get("low_52w")
        high_52w = stats.get("high_52w")
        return {
            "price": price,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "drawdown_from_high_pct": calc_drawdown_from_high_pct(price, high_52w),
            "pe": pe,
            "pe_ttm": pe_ttm,
            "pe_static": pe_static,
            "pe_dynamic": pe_dynamic,
            "pb": pb,
            "ps": ps,
            "market_cap_yuan": market_cap_yuan,
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

    def fetch_financials(self, code: str, *, fast: bool = False) -> StockFinancials:
        code = normalize_code(code)
        if self.cache is not None:
            cached = self.cache.get("financial", code)
            if cached is not None:
                return deserialize_financials(cached)

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_financial_abstract_ths(symbol=code)

        try:
            if fast:
                df = call_with_timeout(
                    _fetch,
                    timeout_sec=FAST_REQUEST_TIMEOUT_SEC,
                    retries=FAST_REQUEST_RETRIES,
                )
            else:
                df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            return StockFinancials(code=code, market=Market.A, annual=[])

        financials = self._parse_financials(code, df)
        rd_map = self._fetch_rd_expense_map(code, fast=fast)
        if rd_map:
            financials = self._apply_rd_expense_map(financials, rd_map)
        if self.cache is not None:
            self.cache.set("financial", code, serialize_financials(financials))
        return financials

    def _fetch_rd_expense_map(self, code: str, *, fast: bool) -> dict[date, float]:
        cache_key = f"rd_expense_{code}"
        if self.cache is not None:
            cached = self.cache.get("financial", cache_key)
            if cached is not None:
                return {
                    date.fromisoformat(key): float(value)
                    for key, value in cached.items()
                    if value is not None
                }

        self._throttle()

        def _fetch() -> pd.DataFrame:
            return ak.stock_financial_benefit_ths(symbol=code, indicator="按报告期")

        try:
            if fast:
                df = call_with_timeout(
                    _fetch,
                    timeout_sec=FAST_REQUEST_TIMEOUT_SEC,
                    retries=FAST_REQUEST_RETRIES,
                )
            else:
                df = call_with_retry(_fetch, retries=self.network_retries)
        except Exception:
            return {}

        rd_map = self._parse_rd_expense_map(df)
        if self.cache is not None:
            payload = {
                key.isoformat(): value for key, value in rd_map.items()
            }
            self.cache.set("financial", cache_key, payload)
        return rd_map

    @staticmethod
    def _parse_rd_expense_map(df: pd.DataFrame | None) -> dict[date, float]:
        if df is None or df.empty or "报告期" not in df.columns:
            return {}
        rd_map: dict[date, float] = {}
        for _, row in df.iterrows():
            report_date = parse_report_date(row.get("报告期"))
            if report_date is None or report_date > date.today():
                continue
            rd_yuan = parse_money_to_yuan(row.get("研发费用"))
            if rd_yuan is None:
                continue
            rd_map[report_date] = rd_yuan
        return rd_map

    @staticmethod
    def _apply_rd_expense_map(
        financials: StockFinancials,
        rd_map: dict[date, float],
    ) -> StockFinancials:
        if not rd_map:
            return financials
        annual = [
            replace(
                item,
                rd_expense_yuan=rd_map.get(item.report_date, item.rd_expense_yuan),
            )
            for item in financials.annual
        ]
        return StockFinancials(
            code=financials.code,
            market=financials.market,
            annual=annual,
        )

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
                        coalesce_row(row, "营业总收入", "营业收入")
                    ),
                    gross_margin_pct=parse_percent(row.get("销售毛利率")),
                    net_margin_pct=parse_percent(row.get("销售净利率")),
                    operating_cashflow_per_share=parse_number(row.get("每股经营现金流")),
                    operating_cashflow_yuan=parse_money_to_yuan(row.get("经营现金流量净额")),
                    debt_ratio_pct=parse_percent(row.get("资产负债率")),
                    roe_pct=parse_percent(row.get("净资产收益率")),
                    eps_basic=parse_number(row.get("基本每股收益")),
                )
            )
        annual.sort(key=lambda item: item.report_date)
        return StockFinancials(code=code, market=Market.A, annual=annual)


def _strip_market_prefix(code: str) -> str:
    text = str(code).strip().lower()
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _normalize_sina_spot_df(df: pd.DataFrame) -> pd.DataFrame:
    """Map Sina spot columns to the East Money-like schema used downstream."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["代码", "名称", "最新价", "市盈率-动态", "市净率"])
    out = pd.DataFrame(
        {
            "代码": df["代码"].map(_strip_market_prefix).map(normalize_code),
            "名称": df["名称"],
            "最新价": pd.to_numeric(df["最新价"], errors="coerce"),
            "市盈率-动态": pd.NA,
            "市净率": pd.NA,
        }
    )
    return out


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


def _parse_market_cap_yuan(value: object) -> float | None:
    """Parse total market cap to yuan (East Money bulk spot uses yuan)."""
    parsed = parse_money_to_yuan(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def build_data_provider(name: str, **kwargs: object) -> MarketDataProvider:
    if name == "akshare":
        return AkshareDataProvider(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported data source: {name}")
