from __future__ import annotations

from datetime import datetime

from stock_mining.models import CandidateHit
from stock_mining.state.store import UserStateStore


def _current_price(hit: CandidateHit) -> float | None:
    raw = hit.metrics.get("price")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def filter_candidates(
    hits: list[CandidateHit],
    state: UserStateStore,
    *,
    now: datetime | None = None,
    drop_ratio: float | None = None,
) -> list[CandidateHit]:
    now = now or datetime.now()
    state.release_expired_dispositions(now=now)
    filtered: list[CandidateHit] = []
    for hit in hits:
        if state.should_suppress_daily_push(
            hit.stock_key,
            _current_price(hit),
            now=now,
            drop_ratio=drop_ratio if drop_ratio is not None else 0.10,
        ):
            continue
        filtered.append(hit)
    return filtered
