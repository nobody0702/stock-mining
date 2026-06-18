from __future__ import annotations

import re

from stock_mining.llm.dimensions import AnalysisDimension


def parse_markdown_table(text: str, dimensions: tuple[AnalysisDimension, ...]) -> dict[str, str]:
    rows = _extract_table_rows(text)
    if not rows:
        return {}

    header = rows[0]
    if len(header) < 2:
        return {}

    parsed: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        label = row[0].strip()
        content = row[1].strip()
        dimension_id = _match_dimension(label, dimensions)
        if dimension_id is not None and content:
            parsed[dimension_id] = content
    return parsed


def missing_dimensions(parsed: dict[str, str], dimensions: tuple[AnalysisDimension, ...]) -> list[str]:
    return [dimension.id for dimension in dimensions if dimension.id not in parsed]


def _extract_table_rows(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    rows: list[list[str]] = []
    for line in lines:
        if re.match(r"^\|\s*-+", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _match_dimension(label: str, dimensions: tuple[AnalysisDimension, ...]) -> str | None:
    normalized = label.strip().lower()
    for dimension in dimensions:
        if normalized == dimension.id.lower():
            return dimension.id
        if normalized == dimension.label.lower():
            return dimension.id
        if dimension.label.lower() in normalized or normalized in dimension.label.lower():
            return dimension.id
    return None
