from __future__ import annotations

from typing import Any

from stock_mining.utils import parse_number, parse_percent


def parse_hk_indicator_metrics(row: Any) -> dict[str, float | None]:
    """Parse PE/PB/dividend/market cap from stock_hk_financial_indicator_em row."""
    pe = parse_number(_coalesce(row, "市盈率", "PE"))
    pb = parse_number(_coalesce(row, "市净率", "PB"))
    ps = parse_number(_coalesce(row, "市销率", "PS"))
    dividend = parse_percent(_coalesce(row, "股息率TTM(%)", "股息率"))
    market_cap = parse_number(_coalesce(row, "总市值(港元)", "总市值"))
    return {
        "pe": pe,
        "pb": pb,
        "ps": ps,
        "dividend_yield_pct": dividend,
        "market_cap_yuan": market_cap,
    }


def _coalesce(row: Any, *keys: str) -> object:
    for key in keys:
        if key in row.index and row[key] is not None:
            return row[key]
        if isinstance(row, dict) and key in row and row[key] is not None:
            return row[key]
    return None
