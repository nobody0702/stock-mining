from __future__ import annotations

import time
from typing import Iterable

import pandas as pd
import requests

from stock_mining.data.http_retry import call_with_retry
from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.models import StockInfo

_SINA_HK_GGT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHKStockData"
)
_SINA_HK_GGT_NODE = "hgt_hk"
_SINA_PAGE_SIZE = 60
_SINA_MAX_PAGES = 20


def fetch_hk_ggt_constituents_sina(
    *,
    network_retries: int = 3,
    request_interval_sec: float = 0.15,
) -> list[StockInfo]:
    """Fetch Stock Connect HK constituents from Sina (fallback when East Money fails)."""

    def _fetch_all_pages() -> list[dict]:
        rows: list[dict] = []
        last_request_at = 0.0
        for page in range(1, _SINA_MAX_PAGES + 1):
            if request_interval_sec > 0:
                elapsed = time.time() - last_request_at
                if elapsed < request_interval_sec:
                    time.sleep(request_interval_sec - elapsed)
            last_request_at = time.time()

            response = requests.get(
                _SINA_HK_GGT_URL,
                params={
                    "page": str(page),
                    "num": str(_SINA_PAGE_SIZE),
                    "sort": "symbol",
                    "asc": "1",
                    "node": _SINA_HK_GGT_NODE,
                    "_s_r_a": "init",
                },
                timeout=20,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload:
                break
            rows.extend(payload)
        return rows

    raw_rows = call_with_retry(_fetch_all_pages, retries=network_retries)
    if not raw_rows:
        raise RuntimeError("Sina 港股通成份股列表为空")

    stocks = _rows_to_stock_info(raw_rows)
    if not stocks:
        raise RuntimeError("Sina 港股通成份股解析失败")
    return stocks


def _rows_to_stock_info(rows: Iterable[dict]) -> list[StockInfo]:
    seen: set[str] = set()
    stocks: list[StockInfo] = []
    for row in rows:
        code = normalize_stock_code(str(row.get("symbol", "")), Market.HK)
        if not code or code in seen:
            continue
        seen.add(code)
        name = str(row.get("name", code)).strip()
        stocks.append(StockInfo(code=code, name=name, market=Market.HK))
    return stocks


def hk_ggt_rows_as_dataframe(stocks: list[StockInfo]) -> pd.DataFrame:
    return pd.DataFrame(
        {"代码": [stock.code for stock in stocks], "名称": [stock.name for stock in stocks]}
    )
