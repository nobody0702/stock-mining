from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stock_mining.models import AnnualMetrics, StockFinancials


class SqliteCache:
    def __init__(self, cache_dir: str | Path, ttl_hours: int = 12) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "cache.sqlite3"
        self.ttl = timedelta(hours=ttl_hours)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv_cache (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, key)
                )
                """
            )

    def get(self, namespace: str, key: str) -> Any | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload, updated_at FROM kv_cache WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        updated_at = datetime.fromisoformat(row[1])
        if datetime.now() - updated_at > self.ttl:
            return None
        return json.loads(row[0])

    def get_allow_stale(self, namespace: str, key: str) -> Any | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM kv_cache WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, namespace: str, key: str, payload: Any) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kv_cache(namespace, key, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (namespace, key, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
            )


def serialize_financials(financials: StockFinancials) -> dict[str, Any]:
    return {
        "code": financials.code,
        "annual": [
            {
                "report_date": item.report_date.isoformat(),
                "net_profit_yuan": item.net_profit_yuan,
                "gross_margin_pct": item.gross_margin_pct,
                "net_margin_pct": item.net_margin_pct,
                "operating_cashflow_per_share": item.operating_cashflow_per_share,
                "debt_ratio_pct": item.debt_ratio_pct,
                "roe_pct": item.roe_pct,
            }
            for item in financials.annual
        ],
    }


def deserialize_financials(payload: dict[str, Any]) -> StockFinancials:
    from datetime import date

    annual = [
        AnnualMetrics(
            report_date=date.fromisoformat(item["report_date"]),
            net_profit_yuan=item.get("net_profit_yuan"),
            gross_margin_pct=item.get("gross_margin_pct"),
            net_margin_pct=item.get("net_margin_pct"),
            operating_cashflow_per_share=item.get("operating_cashflow_per_share"),
            debt_ratio_pct=item.get("debt_ratio_pct"),
            roe_pct=item.get("roe_pct"),
        )
        for item in payload.get("annual", [])
    ]
    return StockFinancials(code=payload["code"], annual=annual)
