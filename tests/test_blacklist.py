from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from stock_mining.models import CandidateHit
from stock_mining.markets.base import Market
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.state.store import UserStateStore


@pytest.fixture
def store(tmp_path):
    return UserStateStore(tmp_path / "state.sqlite3")


def _hit(code: str = "688001") -> CandidateHit:
    return CandidateHit(
        code=code,
        name="样本",
        market=Market.A,
        track="profitable_growth",
        score=80,
        metrics={},
    )


def test_blacklist_legacy_state_only(store):
    hit = _hit()
    entry_id = store.add_blacklist_pending(hit.stock_key, hit.name, hit.market.value, "测试", 30)
    store.approve_blacklist(entry_id)
    assert store.is_blacklisted(hit.stock_key)
    assert filter_candidates([hit], store) == [hit]


def test_blacklist_releases_after_expiry(store):
    hit = _hit()
    now = datetime(2025, 1, 1)
    entry_id = store.add_blacklist_pending(
        hit.stock_key,
        hit.name,
        hit.market.value,
        "测试",
        1,
        now=now,
    )
    store.approve_blacklist(entry_id, now=now)
    assert store.is_blacklisted(hit.stock_key, now=now + timedelta(hours=12))
    store.release_expired_blacklist(now=now + timedelta(days=2))
    assert not store.is_blacklisted(hit.stock_key, now=now + timedelta(days=2))


def test_recommendation_cooldown(store):
    hit = _hit()
    store.mark_studied(hit.stock_key, hit.name, hit.market.value, cooldown_days=30)
    assert store.is_in_recommendation_cooldown(hit.stock_key, cooldown_days=30)


def test_disposition_blocks_dedup(store):
    hit = _hit()
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        "not_interested",
        suppress_days=90,
    )
    assert filter_candidates([hit], store) == []


def test_analysis_pending_to_approved(store):
    hit = _hit()
    entry_id = store.save_analysis_pending(
        hit.stock_key,
        hit.name,
        hit.market.value,
        "moat",
        "护城河较深",
    )
    store.approve_analysis(entry_id, ttl_days=90)
    entry = store.get_valid_analysis(hit.stock_key, "moat")
    assert entry is not None
    assert entry.content == "护城河较深"
