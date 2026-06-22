from __future__ import annotations

from datetime import datetime, timedelta

from stock_mining.models import CandidateHit
from stock_mining.markets.base import Market
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.state.disposition import DispositionKind
from stock_mining.state.store import UserStateStore


def test_dedup_combined(tmp_path):
    store = UserStateStore(tmp_path / "state.sqlite3")
    hit1 = CandidateHit("688001", "A", Market.A, "profitable_growth", 90, {"price": 10.0})
    hit2 = CandidateHit("688002", "B", Market.A, "profitable_growth", 80, {"price": 20.0})

    store.set_stock_disposition(
        hit1.stock_key,
        hit1.name,
        hit1.market.value,
        DispositionKind.WATCHLIST,
    )
    store.set_stock_disposition(
        hit2.stock_key,
        hit2.name,
        hit2.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=30,
    )

    result = filter_candidates([hit1, hit2], store)
    assert result == []


def test_dedup_releases_expired_not_interested(tmp_path):
    store = UserStateStore(tmp_path / "state.sqlite3")
    hit = CandidateHit("688001", "A", Market.A, "profitable_growth", 90, {})
    now = datetime(2025, 1, 1)
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=1,
        now=now,
    )
    assert filter_candidates([hit], store, now=now + timedelta(hours=12)) == []
    store.release_expired_dispositions(now=now + timedelta(days=2))
    assert filter_candidates([hit], store, now=now + timedelta(days=2)) == [hit]
