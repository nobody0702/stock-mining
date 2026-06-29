from __future__ import annotations

from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.models import CandidateHit


def build_stock_key(market: Market | str, code: str) -> str:
    market_value = market.value if isinstance(market, Market) else str(market)
    normalized = normalize_stock_code(code, Market(market_value))
    return f"{market_value}:{normalized}"


def index_by_stock_key(hits: list[CandidateHit]) -> dict[str, CandidateHit]:
    return {hit.stock_key: hit for hit in hits}


def index_by_code(hits: list[CandidateHit], *, market: Market | str = Market.A) -> dict[str, CandidateHit]:
    market_value = market.value if isinstance(market, Market) else str(market)
    indexed: dict[str, CandidateHit] = {}
    for hit in hits:
        if hit.market.value != market_value:
            continue
        code = normalize_stock_code(hit.code, hit.market)
        indexed[code] = hit
    return indexed


def lookup_by_code(
    hits: list[CandidateHit],
    code: str,
    *,
    market: Market | str = Market.A,
) -> CandidateHit | None:
    return index_by_code(hits, market=market).get(normalize_stock_code(code, Market(market)))


def lookup_by_stock_key(hits: list[CandidateHit], stock_key: str) -> CandidateHit | None:
    return index_by_stock_key(hits).get(stock_key)
