from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from stock_mining.markets.tags import normalize_legacy_stock_key
from stock_mining.state.disposition import (
    DEFAULT_SUPPRESS_DAYS,
    DispositionKind,
    StockDispositionEntry,
)

_KIND_FILES: dict[str, str] = {
    DispositionKind.NOT_INTERESTED: "not_interested.json",
    DispositionKind.TOO_EXPENSIVE: "too_expensive.json",
    DispositionKind.WATCHLIST: "watchlist.json",
}


class DispositionFileStore:
    """Git-friendly JSON files for user stock dispositions."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        for filename in _KIND_FILES.values():
            path = self.directory / filename
            if not path.exists():
                path.write_text("[]\n", encoding="utf-8")

    def is_empty(self) -> bool:
        return all(len(self._load(kind)) == 0 for kind in _KIND_FILES)

    def import_entries(self, grouped: dict[str, list[dict]]) -> int:
        total = 0
        for kind in _KIND_FILES:
            entries = grouped.get(kind, [])
            self._save(kind, entries)
            total += len(entries)
        return total

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
        set_at: datetime | None = None,
        release_at: datetime | None = None,
    ) -> None:
        now = now or datetime.now()
        set_at = set_at or now
        ref_price = reference_price
        computed_release_at = release_at

        if disposition == DispositionKind.NOT_INTERESTED:
            computed_release_at = computed_release_at or set_at + timedelta(days=suppress_days)
            ref_price = None
        elif disposition == DispositionKind.TOO_EXPENSIVE:
            computed_release_at = computed_release_at or set_at + timedelta(days=suppress_days)
        elif disposition == DispositionKind.WATCHLIST:
            computed_release_at = None
            ref_price = None
        else:
            raise ValueError(f"Unknown disposition: {disposition}")

        self._remove_stock_key(stock_key)
        payload = {
            "stock_key": normalize_legacy_stock_key(stock_key),
            "name": name,
            "market": market,
            "reference_price": ref_price,
            "set_at": set_at.isoformat(),
            "release_at": computed_release_at.isoformat() if computed_release_at else None,
        }
        entries = self._load(disposition)
        entries.append(payload)
        self._save(disposition, entries)

    def clear_stock_disposition(self, stock_key: str) -> None:
        self._remove_stock_key(stock_key)

    def get_stock_disposition(
        self,
        stock_key: str,
        *,
        active_only: bool = True,
    ) -> StockDispositionEntry | None:
        for kind in _KIND_FILES:
            for index, raw in enumerate(self._load(kind), start=1):
                if normalize_legacy_stock_key(str(raw["stock_key"])) != normalize_legacy_stock_key(stock_key):
                    continue
                entry = self._to_entry(raw, kind, index)
                if active_only:
                    return entry
                return entry
        return None

    def list_stock_dispositions(
        self,
        *,
        disposition: str | None = None,
        active_only: bool = True,
    ) -> list[StockDispositionEntry]:
        kinds = [disposition] if disposition is not None else list(_KIND_FILES)
        results: list[StockDispositionEntry] = []
        for kind in kinds:
            for index, raw in enumerate(self._load(kind), start=1):
                entry = self._to_entry(raw, kind, index)
                if active_only or entry.status == "active":
                    results.append(entry)
        results.sort(key=lambda item: item.set_at, reverse=True)
        return results

    def release_expired_dispositions(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now()
        released = 0
        for kind in (DispositionKind.NOT_INTERESTED, DispositionKind.TOO_EXPENSIVE):
            kept: list[dict] = []
            for raw in self._load(kind):
                release_at = raw.get("release_at")
                if release_at and datetime.fromisoformat(release_at) <= now:
                    released += 1
                    continue
                kept.append(raw)
            self._save(kind, kept)
        return released

    def _remove_stock_key(self, stock_key: str) -> None:
        normalized = normalize_legacy_stock_key(stock_key)
        for kind in _KIND_FILES:
            entries = [
                item
                for item in self._load(kind)
                if normalize_legacy_stock_key(str(item["stock_key"])) != normalized
            ]
            self._save(kind, entries)

    def _path(self, kind: str) -> Path:
        return self.directory / _KIND_FILES[kind]

    def _load(self, kind: str) -> list[dict]:
        return json.loads(self._path(kind).read_text(encoding="utf-8"))

    def _save(self, kind: str, entries: list[dict]) -> None:
        self._path(kind).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _to_entry(raw: dict, kind: str, index: int) -> StockDispositionEntry:
        ref = raw.get("reference_price")
        release = raw.get("release_at")
        return StockDispositionEntry(
            id=index,
            stock_key=normalize_legacy_stock_key(str(raw["stock_key"])),
            name=str(raw["name"]),
            market=str(raw["market"]),
            disposition=kind,
            reference_price=float(ref) if ref is not None else None,
            set_at=datetime.fromisoformat(str(raw["set_at"])),
            release_at=datetime.fromisoformat(release) if release else None,
            status="active",
        )


def migrate_sqlite_dispositions(
    db_path: Path,
    file_store: DispositionFileStore,
) -> int:
    """One-time import from legacy stock_dispositions SQLite table."""
    if not file_store.is_empty():
        return 0
    if not db_path.exists():
        return 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT stock_key, name, market, disposition, reference_price, set_at, release_at
                FROM stock_dispositions
                WHERE status='active'
                ORDER BY set_at ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

    grouped: dict[str, list[dict]] = {kind: [] for kind in _KIND_FILES}
    for row in rows:
        kind = row["disposition"]
        if kind not in grouped:
            continue
        ref = row["reference_price"]
        release = row["release_at"]
        grouped[kind].append(
            {
                "stock_key": row["stock_key"],
                "name": row["name"],
                "market": row["market"],
                "reference_price": float(ref) if ref is not None else None,
                "set_at": row["set_at"],
                "release_at": release,
            }
        )

    return file_store.import_entries(grouped)
