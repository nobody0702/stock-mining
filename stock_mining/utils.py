from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
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
    if isinstance(value, float):
        if value != value:
            return None
        return value
    if isinstance(value, int):
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


def coalesce_row(row: object, *keys: str) -> object | None:
    getter = getattr(row, "get", None)
    if getter is None:
        return None
    for key in keys:
        value = getter(key)
        if value is None:
            continue
        if isinstance(value, float) and value != value:
            continue
        if isinstance(value, str) and value.strip().lower() in {"", "nan", "none", "--"}:
            continue
        return value
    return None


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


def load_project_env(env_path: str | Path, *, override: bool = False) -> bool:
    """Load KEY=VALUE lines from a .env file into os.environ."""
    path = Path(env_path)
    if not path.is_file():
        return False
    loaded = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not override and key in os.environ and os.environ[key]:
            continue
        os.environ[key] = value
        loaded = True
    return loaded


def copy_to_clipboard(text: str) -> tuple[bool, str | None]:
    """Copy text to the system clipboard. Returns (ok, error_message)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
            )
            return True, None
        if system == "Linux":
            if shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True,
                )
                return True, None
            if shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    check=True,
                )
                return True, None
            return False, "未找到 xclip 或 xsel，无法写入剪贴板"
        if system == "Windows":
            subprocess.run(
                ["clip"],
                input=text.encode("utf-16le"),
                check=True,
            )
            return True, None
        return False, f"当前系统 ({system}) 暂不支持自动复制"
    except (OSError, subprocess.CalledProcessError) as exc:
        return False, str(exc)
