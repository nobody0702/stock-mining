from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from stock_mining.models import CandidateHit
from stock_mining.markets.base import Market
from stock_mining.pipeline.dedup import filter_candidates
from stock_mining.state.disposition import (
    DispositionKind,
    StockDispositionEntry,
    should_suppress_daily_push,
)
from stock_mining.state.store import UserStateStore


@pytest.fixture
def store(tmp_path):
    return UserStateStore(tmp_path / "state.sqlite3")


def _hit(code: str = "688001", *, price: float | None = None) -> CandidateHit:
    metrics = {"price": price} if price is not None else {}
    return CandidateHit(
        code=code,
        name="样本",
        market=Market.A,
        track="profitable_growth",
        score=80,
        metrics=metrics,
    )


def _entry(
    kind: str,
    *,
    reference_price: float | None = None,
    set_at: datetime | None = None,
    release_at: datetime | None = None,
) -> StockDispositionEntry:
    now = set_at or datetime(2025, 6, 1)
    return StockDispositionEntry(
        id=1,
        stock_key="a:688001",
        name="样本",
        market="a",
        disposition=kind,
        reference_price=reference_price,
        set_at=now,
        release_at=release_at,
        status="active",
    )


def test_not_interested_suppresses_until_release():
    now = datetime(2025, 6, 1)
    entry = _entry(
        DispositionKind.NOT_INTERESTED,
        release_at=now + timedelta(days=90),
    )
    assert should_suppress_daily_push(entry, current_price=None, now=now)
    assert should_suppress_daily_push(entry, current_price=None, now=now + timedelta(days=89))
    assert not should_suppress_daily_push(entry, current_price=None, now=now + timedelta(days=90))


def test_not_interested_st_destar_allows_reentry():
    now = datetime(2025, 6, 1)
    entry = StockDispositionEntry(
        id=1,
        stock_key="a:600001",
        name="*ST示例",
        market="a",
        disposition=DispositionKind.NOT_INTERESTED,
        reference_price=None,
        set_at=now,
        release_at=now + timedelta(days=365),
        status="active",
    )
    assert not should_suppress_daily_push(
        entry, current_price=None, now=now, current_name="示例股份"
    )
    assert should_suppress_daily_push(
        entry, current_price=None, now=now, current_name="*ST示例"
    )
    # Non-ST archived name must still suppress even if current name is clean
    plain = _entry(
        DispositionKind.NOT_INTERESTED,
        release_at=now + timedelta(days=90),
    )
    assert should_suppress_daily_push(
        plain, current_price=None, now=now, current_name="样本"
    )


def test_dedup_allows_st_destar_candidate(store):
    now = datetime(2025, 6, 1)
    store.set_stock_disposition(
        "a:600001",
        "*ST摘帽",
        "a",
        DispositionKind.NOT_INTERESTED,
        suppress_days=365,
        now=now,
    )
    hit = CandidateHit(
        code="600001",
        name="摘帽股份",
        market=Market.A,
        track="profitable_growth",
        score=70,
        metrics={"price": 10.0},
    )
    still_st = CandidateHit(
        code="600002",
        name="*ST还在",
        market=Market.A,
        track="profitable_growth",
        score=70,
        metrics={},
    )
    store.set_stock_disposition(
        still_st.stock_key,
        "*ST还在",
        "a",
        DispositionKind.NOT_INTERESTED,
        suppress_days=365,
        now=now,
    )
    result = filter_candidates([hit, still_st], store, now=now)
    assert [item.code for item in result] == ["600001"]


def test_too_expensive_suppresses_until_price_drop_or_release():
    now = datetime(2025, 6, 1)
    entry = _entry(
        DispositionKind.TOO_EXPENSIVE,
        reference_price=100.0,
        release_at=now + timedelta(days=90),
    )
    assert should_suppress_daily_push(entry, current_price=95.0, now=now)
    assert not should_suppress_daily_push(entry, current_price=90.0, now=now)
    assert not should_suppress_daily_push(entry, current_price=100.0, now=now + timedelta(days=90))


def test_watchlist_always_suppresses():
    entry = _entry(DispositionKind.WATCHLIST)
    assert should_suppress_daily_push(entry, current_price=50.0, now=datetime(2025, 6, 1))


def test_store_disposition_mutually_exclusive(store):
    hit = _hit()
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.WATCHLIST,
    )
    assert store.get_stock_disposition(hit.stock_key).disposition == DispositionKind.WATCHLIST

    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=90,
    )
    entry = store.get_stock_disposition(hit.stock_key)
    assert entry.disposition == DispositionKind.NOT_INTERESTED
    assert entry.reference_price is None
    assert len(store.list_stock_dispositions(active_only=True)) == 1


def test_store_too_expensive_records_reference_price(store):
    hit = _hit(price=100.0)
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.TOO_EXPENSIVE,
        reference_price=100.0,
    )
    entry = store.get_stock_disposition(hit.stock_key)
    assert entry.reference_price == 100.0


def test_clear_watchlist_allows_push(store):
    hit = _hit()
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.WATCHLIST,
    )
    assert store.should_suppress_daily_push(hit.stock_key, None)
    store.clear_stock_disposition(hit.stock_key)
    assert store.get_stock_disposition(hit.stock_key) is None
    assert not store.should_suppress_daily_push(hit.stock_key, None)


def test_release_expired_dispositions(store):
    hit = _hit()
    now = datetime(2025, 1, 1)
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=1,
        now=now,
    )
    assert store.should_suppress_daily_push(hit.stock_key, None, now=now + timedelta(hours=12))
    released = store.release_expired_dispositions(now=now + timedelta(days=2))
    assert released == 1
    assert store.get_stock_disposition(hit.stock_key) is None


def test_disposition_persisted_to_json_files(store, tmp_path):
    hit = _hit()
    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.WATCHLIST,
    )
    watchlist_path = tmp_path / "dispositions" / "watchlist.json"
    assert watchlist_path.exists()
    payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["stock_key"] == hit.stock_key

    store.set_stock_disposition(
        hit.stock_key,
        hit.name,
        hit.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=90,
    )
    assert json.loads(watchlist_path.read_text(encoding="utf-8")) == []
    not_interested_path = tmp_path / "dispositions" / "not_interested.json"
    assert len(json.loads(not_interested_path.read_text(encoding="utf-8"))) == 1


def test_migrate_sqlite_dispositions_to_json(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    disp_dir = tmp_path / "dispositions"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE stock_dispositions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                market TEXT NOT NULL,
                disposition TEXT NOT NULL,
                reference_price REAL,
                set_at TEXT NOT NULL,
                release_at TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            );
            INSERT INTO stock_dispositions(
                stock_key, name, market, disposition, reference_price, set_at, release_at, status
            ) VALUES (
                'a:688001', '样本A', 'a', 'watchlist', NULL, '2025-06-01T10:00:00', NULL, 'active'
            );
            """
        )

    store = UserStateStore(db_path, dispositions_dir=disp_dir)
    assert len(store.list_stock_dispositions(disposition=DispositionKind.WATCHLIST)) == 1
    payload = json.loads((disp_dir / "watchlist.json").read_text(encoding="utf-8"))
    assert payload[0]["stock_key"] == "a:688001"


def test_dedup_filters_by_disposition(store):
    hit1 = _hit("688001", price=100.0)
    hit2 = _hit("688002", price=80.0)
    hit3 = _hit("688003", price=50.0)

    store.set_stock_disposition(
        hit1.stock_key,
        hit1.name,
        hit1.market.value,
        DispositionKind.NOT_INTERESTED,
        suppress_days=90,
    )
    store.set_stock_disposition(
        hit2.stock_key,
        hit2.name,
        hit2.market.value,
        DispositionKind.TOO_EXPENSIVE,
        reference_price=80.0,
        suppress_days=90,
    )
    store.set_stock_disposition(
        hit3.stock_key,
        hit3.name,
        hit3.market.value,
        DispositionKind.WATCHLIST,
    )

    result = filter_candidates([hit1, hit2, hit3], store)
    assert result == []

    hit2_cheaper = _hit("688002", price=71.0)
    result = filter_candidates([hit1, hit2_cheaper, hit3], store)
    assert result == [hit2_cheaper]
