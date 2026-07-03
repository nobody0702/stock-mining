from __future__ import annotations

from dataclasses import replace
from typing import Any

from stock_mining.models import MarketSnapshot
from stock_mining.utils import parse_number


def resolve_primary_pe(
    *,
    pe_ttm: float | None = None,
    pe_dynamic: float | None = None,
    pe_static: float | None = None,
    fallback: float | None = None,
) -> float | None:
    """Pick the headline PE for filters/scoring: TTM > dynamic > static > legacy."""
    for value in (pe_ttm, pe_dynamic, pe_static, fallback):
        if value is not None:
            return value
    return None


def parse_pe_from_value_em_row(row: Any) -> dict[str, float | None]:
    """East Money stock_value_em: PE(TTM) and PE(静)."""
    return {
        "pe_ttm": parse_number(_row_get(row, "PE(TTM)")),
        "pe_static": parse_number(_row_get(row, "PE(静)")),
    }


def parse_pe_from_spot_row(row: Any) -> dict[str, float | None]:
    """East Money bulk spot: 市盈率-动态 only."""
    pe_dynamic = parse_number(_row_get(row, "市盈率-动态"))
    return {
        "pe_dynamic": pe_dynamic,
        "pe": pe_dynamic,
    }


def merge_pe_fields(
    *,
    pe_ttm: float | None = None,
    pe_static: float | None = None,
    pe_dynamic: float | None = None,
    fallback_pe: float | None = None,
) -> dict[str, float | None]:
    primary = resolve_primary_pe(
        pe_ttm=pe_ttm,
        pe_dynamic=pe_dynamic,
        pe_static=pe_static,
        fallback=fallback_pe,
    )
    return {
        "pe_ttm": pe_ttm,
        "pe_static": pe_static,
        "pe_dynamic": pe_dynamic,
        "pe": primary,
    }


def replace_market_snapshot(snapshot: MarketSnapshot, /, **changes: Any) -> MarketSnapshot:
    updated = replace(snapshot, **changes)
    if any(key in changes for key in ("pe_ttm", "pe_static", "pe_dynamic")) and "pe" not in changes:
        primary = resolve_primary_pe(
            pe_ttm=updated.pe_ttm,
            pe_dynamic=updated.pe_dynamic,
            pe_static=updated.pe_static,
            fallback=updated.pe,
        )
        if primary is not None:
            updated = replace(updated, pe=primary)
    return updated


def _row_get(row: Any, key: str) -> object:
    if hasattr(row, "get"):
        return row.get(key)
    if key in row.index:
        return row[key]
    return None
