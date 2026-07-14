from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stock_mining.models import AnnualMetrics, StockFinancials


class SqliteCache:
    def __init__(
        self,
        cache_dir: str | Path,
        ttl_hours: int = 12,
        namespace_prefix: str = "",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "cache.sqlite3"
        self.ttl = timedelta(hours=ttl_hours)
        self.namespace_prefix = namespace_prefix
        self._init_db()

    def _ns(self, namespace: str) -> str:
        if not self.namespace_prefix:
            return namespace
        return f"{self.namespace_prefix}:{namespace}"

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
        namespace = self._ns(namespace)
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

    def get_many(self, namespace: str, keys: list[str] | set[str]) -> dict[str, Any]:
        """Batch-load non-expired cache entries. Missing/expired keys are omitted."""
        key_list = list(keys)
        if not key_list:
            return {}
        namespace = self._ns(namespace)
        placeholders = ",".join("?" for _ in key_list)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT key, payload, updated_at FROM kv_cache "
                f"WHERE namespace=? AND key IN ({placeholders})",
                (namespace, *key_list),
            ).fetchall()
        now = datetime.now()
        result: dict[str, Any] = {}
        for key, payload, updated_at in rows:
            if now - datetime.fromisoformat(updated_at) > self.ttl:
                continue
            result[str(key)] = json.loads(payload)
        return result

    def get_allow_stale(self, namespace: str, key: str) -> Any | None:
        namespace = self._ns(namespace)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM kv_cache WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, namespace: str, key: str, payload: Any) -> None:
        namespace = self._ns(namespace)
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
        "market": financials.market.value,
        "annual": [
            {
                "report_date": item.report_date.isoformat(),
                "net_profit_yuan": item.net_profit_yuan,
                "revenue_yuan": item.revenue_yuan,
                "gross_margin_pct": item.gross_margin_pct,
                "net_margin_pct": item.net_margin_pct,
                "operating_cashflow_per_share": item.operating_cashflow_per_share,
                "operating_cashflow_yuan": item.operating_cashflow_yuan,
                "debt_ratio_pct": item.debt_ratio_pct,
                "roe_pct": item.roe_pct,
                "eps_basic": item.eps_basic,
                "rd_expense_yuan": item.rd_expense_yuan,
            }
            for item in financials.annual
        ],
    }


def deserialize_financials(payload: dict[str, Any]) -> StockFinancials:
    from datetime import date

    from stock_mining.markets.base import Market

    annual = [
        AnnualMetrics(
            report_date=date.fromisoformat(item["report_date"]),
            net_profit_yuan=item.get("net_profit_yuan"),
            revenue_yuan=item.get("revenue_yuan"),
            gross_margin_pct=item.get("gross_margin_pct"),
            net_margin_pct=item.get("net_margin_pct"),
            operating_cashflow_per_share=item.get("operating_cashflow_per_share"),
            operating_cashflow_yuan=item.get("operating_cashflow_yuan"),
            debt_ratio_pct=item.get("debt_ratio_pct"),
            roe_pct=item.get("roe_pct"),
            eps_basic=item.get("eps_basic"),
            rd_expense_yuan=item.get("rd_expense_yuan"),
        )
        for item in payload.get("annual", [])
    ]
    market = Market(payload.get("market", "a"))
    return StockFinancials(code=payload["code"], market=market, annual=annual)
