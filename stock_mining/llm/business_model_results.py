from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BusinessModelScore:
    code: str
    name: str
    score: int
    description: str = ""
    deduction: str = ""


_CODE_ROW = re.compile(r"^\|\s*(\d{6})\s*\|\s*(.+?)\s*\|\s*([1-5])\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")


def parse_batch_markdown(text: str) -> list[BusinessModelScore]:
    body = text.split("<details>", 1)[0]
    rows: list[BusinessModelScore] = []
    for line in body.splitlines():
        match = _CODE_ROW.match(line.strip())
        if not match:
            continue
        rows.append(
            BusinessModelScore(
                code=match.group(1),
                name=match.group(2).strip(),
                score=int(match.group(3)),
                description=match.group(4).strip(),
                deduction=match.group(5).strip(),
            )
        )
    return rows


def load_business_model_scores(results_dir: Path) -> dict[str, BusinessModelScore]:
    """Load scores keyed by normalized 6-digit code (never by name)."""
    by_code: dict[str, BusinessModelScore] = {}
    for path in sorted(results_dir.glob("batch_*.md")):
        for row in parse_batch_markdown(path.read_text(encoding="utf-8")):
            by_code[row.code] = row
    return by_code
