from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_mining.models import AnnualMetrics


def normalize_code(code: str) -> str:
    return code.strip().split(".")[0].zfill(6)


def is_st_name(name: str) -> bool:
    return "ST" in name.upper()


def is_bj_code(code: str) -> bool:
    return code.startswith(("4", "8", "92"))


def parse_report_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "false":
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_percent(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"false", "nan", "none", "--"}:
        return None
    text = text.replace("%", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"false", "nan", "none", "--"}:
        return None
    text = text.replace(",", "")
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 1e8
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 1e4
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_money_to_yuan(value: object) -> float | None:
    return parse_number(value)


def annual_window(
    financials: list[AnnualMetrics],
    years: int,
    *,
    annual_only: bool = True,
) -> list[AnnualMetrics]:
    rows = list(financials)
    if annual_only:
        rows = [
            item
            for item in rows
            if item.report_date.month == 12 and item.report_date.day == 31
        ]
    rows.sort(key=lambda item: item.report_date)
    return rows[-years:]


def adaptive_annual_window(
    financials: list[AnnualMetrics],
    target_years: int,
    *,
    annual_only: bool = True,
) -> list[AnnualMetrics]:
    """Return up to target_years of annual reports; fewer if history is shorter."""
    return annual_window(financials, target_years, annual_only=annual_only)


def industry_matches_keywords(industry: str | None, keywords: list[str]) -> bool:
    if not industry:
        return False
    return any(keyword in industry for keyword in keywords)


def match_industry_return(
    industry: str | None, returns: dict[str, float]
) -> float | None:
    if not industry or not returns:
        return None
    if industry in returns:
        return returns[industry]
    normalized = industry.replace("行业", "")
    for name, value in returns.items():
        board = name.replace("行业", "")
        if name in industry or industry in name:
            return value
        if board and (board in normalized or normalized in board):
            return value
    return None


def compare(left: float, operator: str, right: float) -> bool:
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator in {"=", "=="}:
        return left == right
    raise ValueError(f"Unsupported operator: {operator}")
