from __future__ import annotations

from datetime import datetime, timedelta

from stock_mining.models import CandidateHit
from stock_mining.markets.base import Market
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.state.store import UserStateStore


def test_dedup_combined(tmp_path):
    store = UserStateStore(tmp_path / "state.sqlite3")
    hit1 = CandidateHit("688001", "A", Market.A, "profitable_growth", 90, {})
    hit2 = CandidateHit("688002", "B", Market.A, "profitable_growth", 80, {})

    store.mark_studied(hit1.stock_key, hit1.name, hit1.market.value, cooldown_days=30)
    entry_id = store.add_blacklist_pending(
        hit2.stock_key,
        hit2.name,
        hit2.market.value,
        "不要",
        180,
    )
    store.approve_blacklist(entry_id)

    result = filter_candidates([hit1, hit2], store, cooldown_days=30)
    assert result == []
