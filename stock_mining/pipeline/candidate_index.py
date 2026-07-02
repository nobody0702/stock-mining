from __future__ import annotations

from stock_mining.markets.base import Market, normalize_stock_code, parse_market
from stock_mining.markets.stock_key import build_stock_key, parse_stock_input
from stock_mining.markets.tags import normalize_legacy_stock_key
from stock_mining.models import CandidateHit


def index_by_stock_key(hits: list[CandidateHit]) -> dict[str, CandidateHit]:
    return {hit.stock_key: hit for hit in hits}


def index_by_code(hits: list[CandidateHit], *, market: Market | str = Market.A) -> dict[str, CandidateHit]:
    market_value = parse_market(market.value if isinstance(market, Market) else str(market))
    indexed: dict[str, CandidateHit] = {}
    for hit in hits:
        if hit.market != market_value:
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
    market_value = parse_market(market.value if isinstance(market, Market) else str(market))
    _, bare = parse_stock_input(code, default_market=market_value)
    return index_by_code(hits, market=market_value).get(bare)


def lookup_by_stock_key(hits: list[CandidateHit], stock_key: str) -> CandidateHit | None:
    normalized = normalize_legacy_stock_key(stock_key)
    return index_by_stock_key(hits).get(normalized)
