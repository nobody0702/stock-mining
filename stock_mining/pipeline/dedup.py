from __future__ import annotations

from datetime import datetime

from stock_mining.models import CandidateHit
from stock_mining.state.store import UserStateStore


def filter_candidates(
    hits: list[CandidateHit],
    state: UserStateStore,
    *,
    cooldown_days: int,
    now: datetime | None = None,
) -> list[CandidateHit]:
    now = now or datetime.now()
    filtered: list[CandidateHit] = []
    for hit in hits:
        if state.is_blacklisted(hit.stock_key, now=now):
            continue
        if state.is_in_recommendation_cooldown(
            hit.stock_key,
            cooldown_days=cooldown_days,
            now=now,
        ):
            continue
        filtered.append(hit)
    return filtered
