from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from stock_mining.data.http_retry import call_with_retry
from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.utils import parse_number

_SINA_HK_SPOT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHKStockData"
)
_SINA_HK_SPOT_NODE = "qbgg_hk"
_SINA_PAGE_SIZE = 60
_SINA_MAX_PAGES = 100


@dataclass(frozen=True)
class HkSinaSpotQuote:
    price: float | None
    low_52w: float | None
    high_52w: float | None


def fetch_hk_spot_quotes_sina(
    *,
    network_retries: int = 3,
    request_interval_sec: float = 0.15,
) -> dict[str, HkSinaSpotQuote]:
    """Bulk HK spot quotes from Sina (thread-safe; no py_mini_racer)."""

    def _fetch_all_pages() -> dict[str, HkSinaSpotQuote]:
        quotes: dict[str, HkSinaSpotQuote] = {}
        last_request_at = 0.0
        for page in range(1, _SINA_MAX_PAGES + 1):
            if request_interval_sec > 0:
                elapsed = time.time() - last_request_at
                if elapsed < request_interval_sec:
                    time.sleep(request_interval_sec - elapsed)
            last_request_at = time.time()

            response = requests.get(
                _SINA_HK_SPOT_URL,
                params={
                    "page": str(page),
                    "num": str(_SINA_PAGE_SIZE),
                    "sort": "symbol",
                    "asc": "1",
                    "node": _SINA_HK_SPOT_NODE,
                    "_s_r_a": "init",
                },
                timeout=20,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload:
                break

            for row in payload:
                code = normalize_stock_code(str(row.get("symbol", "")), Market.HK)
                if not code:
                    continue
                price = parse_number(row.get("lasttrade"))
                low_52w = parse_number(row.get("low_52week"))
                high_52w = parse_number(row.get("high_52week"))
                quotes[code] = HkSinaSpotQuote(
                    price=price,
                    low_52w=low_52w,
                    high_52w=high_52w,
                )
        return quotes

    return call_with_retry(_fetch_all_pages, retries=network_retries)
