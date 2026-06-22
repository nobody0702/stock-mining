from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stock_mining.state.disposition import (
    DEFAULT_SUPPRESS_DAYS,
    DEFAULT_TOO_EXPENSIVE_DROP_RATIO,
    StockDispositionEntry,
    should_suppress_daily_push,
)
from stock_mining.state.disposition_store import DispositionFileStore, migrate_sqlite_dispositions


@dataclass(frozen=True)
class BlacklistEntry:
    id: int
    stock_key: str
    name: str
    market: str
    reason: str
    added_at: datetime
    release_at: datetime
    status: str


@dataclass(frozen=True)
class RecommendationEntry:
    id: int
    stock_key: str
    name: str
    market: str
    recommended_at: datetime
    cooldown_until: datetime | None
    status: str


@dataclass(frozen=True)
class AnalysisEntry:
    id: int
    stock_key: str
    name: str
    market: str
    dimension_id: str
    content: str
    created_at: datetime
    approved_at: datetime | None
    expires_at: datetime | None
    status: str


class UserStateStore:
    def __init__(
        self,
        db_path: str | Path,
        *,
        dispositions_dir: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        disp_dir = dispositions_dir or self.db_path.parent / "dispositions"
        self._dispositions = DispositionFileStore(disp_dir)
        migrate_sqlite_dispositions(self.db_path, self._dispositions)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL,
                    release_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    recommended_at TEXT NOT NULL,
                    cooldown_until TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    dimension_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_at TEXT,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                """
            )

    def add_blacklist_pending(
        self,
        stock_key: str,
        name: str,
        market: str,
        reason: str,
        release_days: int,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now()
        release_at = now + timedelta(days=release_days)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO blacklist(stock_key, name, market, reason, added_at, release_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (stock_key, name, market, reason, now.isoformat(), release_at.isoformat()),
            )
            return int(cursor.lastrowid)

    def approve_blacklist(self, entry_id: int, *, now: datetime | None = None) -> None:
        now = now or datetime.now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE blacklist SET status='active' WHERE id=? AND status='pending'",
                (entry_id,),
            )

    def is_blacklisted(self, stock_key: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT release_at, status FROM blacklist
                WHERE stock_key=? AND status IN ('pending', 'active')
                """,
                (stock_key,),
            ).fetchall()
        for row in rows:
            if row["status"] != "active":
                continue
            release_at = datetime.fromisoformat(row["release_at"])
            if release_at > now:
                return True
        return False

    def list_blacklist(self, *, include_released: bool = False) -> list[BlacklistEntry]:
        with self._connect() as conn:
            if include_released:
                rows = conn.execute("SELECT * FROM blacklist ORDER BY added_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM blacklist WHERE status != 'released' ORDER BY added_at DESC"
                ).fetchall()
        return [self._row_to_blacklist(row) for row in rows]

    def release_expired_blacklist(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE blacklist SET status='released'
                WHERE status='active' AND release_at <= ?
                """,
                (now.isoformat(),),
            )
            return cursor.rowcount

    def record_recommendation_pending(
        self,
        stock_key: str,
        name: str,
        market: str,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recommendations(stock_key, name, market, recommended_at, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (stock_key, name, market, now.isoformat()),
            )
            return int(cursor.lastrowid)

    def approve_recommendation(
        self,
        entry_id: int,
        cooldown_days: int,
        *,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now()
        cooldown_until = now + timedelta(days=cooldown_days)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE recommendations
                SET status='active', cooldown_until=?
                WHERE id=? AND status='pending'
                """,
                (cooldown_until.isoformat(), entry_id),
            )

    def mark_studied(
        self,
        stock_key: str,
        name: str,
        market: str,
        cooldown_days: int,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now()
        cooldown_until = now + timedelta(days=cooldown_days)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO recommendations(stock_key, name, market, recommended_at, cooldown_until, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (stock_key, name, market, now.isoformat(), cooldown_until.isoformat()),
            )
            return int(cursor.lastrowid)

    def is_in_recommendation_cooldown(
        self,
        stock_key: str,
        *,
        cooldown_days: int,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT cooldown_until, status FROM recommendations
                WHERE stock_key=? AND status='active'
                ORDER BY recommended_at DESC
                """,
                (stock_key,),
            ).fetchall()
        for row in rows:
            if row["cooldown_until"] is None:
                continue
            cooldown_until = datetime.fromisoformat(row["cooldown_until"])
            if cooldown_until > now:
                return True
        return False

    def list_recommendations(self, limit: int = 50) -> list[RecommendationEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recommendations ORDER BY recommended_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_recommendation(row) for row in rows]

    def save_analysis_pending(
        self,
        stock_key: str,
        name: str,
        market: str,
        dimension_id: str,
        content: str,
        *,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_cache(
                    stock_key, name, market, dimension_id, content, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (stock_key, name, market, dimension_id, content, now.isoformat()),
            )
            return int(cursor.lastrowid)

    def approve_analysis(self, entry_id: int, ttl_days: int, *, now: datetime | None = None) -> None:
        now = now or datetime.now()
        expires_at = now + timedelta(days=ttl_days)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_cache
                SET status='approved', approved_at=?, expires_at=?
                WHERE id=? AND status='pending'
                """,
                (now.isoformat(), expires_at.isoformat(), entry_id),
            )

    def reject_analysis(self, entry_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE analysis_cache SET status='rejected' WHERE id=? AND status='pending'",
                (entry_id,),
            )

    def get_valid_analysis(
        self,
        stock_key: str,
        dimension_id: str,
        *,
        now: datetime | None = None,
    ) -> AnalysisEntry | None:
        now = now or datetime.now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM analysis_cache
                WHERE stock_key=? AND dimension_id=? AND status='approved'
                ORDER BY approved_at DESC LIMIT 1
                """,
                (stock_key, dimension_id),
            ).fetchone()
        if row is None:
            return None
        entry = self._row_to_analysis(row)
        if entry.expires_at is not None and entry.expires_at <= now:
            return None
        return entry

    def list_pending_analysis(self) -> list[AnalysisEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_cache WHERE status='pending' ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_analysis(row) for row in rows]

    def list_analysis_for_stock(self, stock_key: str) -> list[AnalysisEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM analysis_cache
                WHERE stock_key=?
                ORDER BY created_at DESC
                """,
                (stock_key,),
            ).fetchall()
        return [self._row_to_analysis(row) for row in rows]

    def set_stock_disposition(
        self,
        stock_key: str,
        name: str,
        market: str,
        disposition: str,
        *,
        reference_price: float | None = None,
        suppress_days: int = DEFAULT_SUPPRESS_DAYS,
        now: datetime | None = None,
    ) -> None:
        self._dispositions.set_stock_disposition(
            stock_key,
            name,
            market,
            disposition,
            reference_price=reference_price,
            suppress_days=suppress_days,
            now=now,
        )

    def clear_stock_disposition(self, stock_key: str) -> None:
        self._dispositions.clear_stock_disposition(stock_key)

    def get_stock_disposition(
        self,
        stock_key: str,
        *,
        active_only: bool = True,
    ) -> StockDispositionEntry | None:
        return self._dispositions.get_stock_disposition(
            stock_key,
            active_only=active_only,
        )

    def list_stock_dispositions(
        self,
        *,
        disposition: str | None = None,
        active_only: bool = True,
    ) -> list[StockDispositionEntry]:
        return self._dispositions.list_stock_dispositions(
            disposition=disposition,
            active_only=active_only,
        )

    def should_suppress_daily_push(
        self,
        stock_key: str,
        current_price: float | None,
        *,
        now: datetime | None = None,
        drop_ratio: float = DEFAULT_TOO_EXPENSIVE_DROP_RATIO,
    ) -> bool:
        now = now or datetime.now()
        entry = self.get_stock_disposition(stock_key)
        return should_suppress_daily_push(
            entry,
            current_price=current_price,
            now=now,
            drop_ratio=drop_ratio,
        )

    def release_expired_dispositions(self, *, now: datetime | None = None) -> int:
        return self._dispositions.release_expired_dispositions(now=now)

    @staticmethod
    def _row_to_blacklist(row: sqlite3.Row) -> BlacklistEntry:
        return BlacklistEntry(
            id=row["id"],
            stock_key=row["stock_key"],
            name=row["name"],
            market=row["market"],
            reason=row["reason"],
            added_at=datetime.fromisoformat(row["added_at"]),
            release_at=datetime.fromisoformat(row["release_at"]),
            status=row["status"],
        )

    @staticmethod
    def _row_to_recommendation(row: sqlite3.Row) -> RecommendationEntry:
        cooldown = row["cooldown_until"]
        return RecommendationEntry(
            id=row["id"],
            stock_key=row["stock_key"],
            name=row["name"],
            market=row["market"],
            recommended_at=datetime.fromisoformat(row["recommended_at"]),
            cooldown_until=datetime.fromisoformat(cooldown) if cooldown else None,
            status=row["status"],
        )

    @staticmethod
    def _row_to_analysis(row: sqlite3.Row) -> AnalysisEntry:
        approved = row["approved_at"]
        expires = row["expires_at"]
        return AnalysisEntry(
            id=row["id"],
            stock_key=row["stock_key"],
            name=row["name"],
            market=row["market"],
            dimension_id=row["dimension_id"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]),
            approved_at=datetime.fromisoformat(approved) if approved else None,
            expires_at=datetime.fromisoformat(expires) if expires else None,
            status=row["status"],
        )
