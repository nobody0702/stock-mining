from __future__ import annotations

from stock_mining.markets.base import Market, normalize_stock_code, parse_market
from stock_mining.markets.stock_key import build_stock_key, parse_stock_input
from stock_mining.markets.tags import normalize_legacy_stock_key
from stock_mining.models import CandidateHit


def index_by_stock_key(hits: list[CandidateHit]) -> dict[str, CandidateHit]:
    return {hit.stock_key: hit for hit in hits}


def dedupe_candidates_by_stock_key(hits: list[CandidateHit]) -> list[CandidateHit]:
    """Keep one row per stock_key (highest score wins).

    When the same stock hits multiple strategies/tracks, merging without
    dedupe makes the review page render duplicate cards that share the same
    disposition but collide / thrash Streamlit widgets on re-runs.
    """
    best: dict[str, CandidateHit] = {}
    sources: dict[str, list[str]] = {}
    tracks: dict[str, list[str]] = {}
    for hit in hits:
        key = hit.stock_key
        source = str(hit.metrics.get("source_strategy") or "")
        if source and source not in sources.setdefault(key, []):
            sources[key].append(source)
        if hit.track and hit.track not in tracks.setdefault(key, []):
            tracks[key].append(hit.track)
        prev = best.get(key)
        if prev is None or hit.score > prev.score:
            best[key] = hit

    out: list[CandidateHit] = []
    for key, hit in best.items():
        metrics = dict(hit.metrics)
        if sources.get(key):
            metrics["source_strategies"] = list(sources[key])
        if tracks.get(key) and len(tracks[key]) > 1:
            metrics["matched_tracks"] = list(tracks[key])
        out.append(
            CandidateHit(
                code=hit.code,
                name=hit.name,
                market=hit.market,
                track=hit.track,
                score=hit.score,
                metrics=metrics,
            )
        )
    out.sort(key=lambda item: item.score, reverse=True)
    return out


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
