from __future__ import annotations

from stock_mining.markets.base import Market, parse_market
from stock_mining.markets.tags import (
    normalize_bare_code,
    normalize_legacy_stock_key,
    parse_tagged_token,
    parse_market_tag,
)


def market_tag(market: Market | str) -> str:
    if isinstance(market, Market):
        return market.value
    return parse_market_tag(str(market))


def build_stock_key(market: Market | str, code: str) -> str:
    tag = market_tag(market)
    bare = normalize_bare_code(tag, _strip_tag_if_present(code))
    return f"{tag}:{bare}"


def parse_stock_key(stock_key: str) -> tuple[Market, str]:
    normalized = normalize_legacy_stock_key(stock_key)
    if ":" not in normalized:
        raise ValueError(f"Invalid stock_key (missing market tag): {stock_key!r}")
    tag, bare = normalized.split(":", 1)
    market = parse_market(tag)
    return market, normalize_bare_code(tag, bare)


def parse_stock_input(token: str, *, default_market: Market = Market.A) -> tuple[Market, str]:
    tag, bare = parse_tagged_token(token, default_tag=default_market.value)
    return parse_market(tag), bare


def _strip_tag_if_present(code: str) -> str:
    text = code.strip()
    if ":" in text and text.split(":", 1)[0].lower() in {"a", "h", "hk", "u"}:
        _, bare = text.split(":", 1)
        return bare
    return text
