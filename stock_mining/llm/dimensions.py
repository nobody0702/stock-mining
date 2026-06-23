from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AnalysisDimension:
    id: str
    label: str
    hint: str
    ttl_days: int
    rubric: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisConfig:
    dimensions: tuple[AnalysisDimension, ...]
    language: str = "simple"
    include_quant_summary: bool = True
    require_rubric_alignment: bool = True


def load_dimensions_config(path: str | Path) -> AnalysisConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)
    prompt_raw = raw.get("prompt", {})
    dimensions = tuple(
        AnalysisDimension(
            id=item["id"],
            label=item["label"],
            hint=str(item.get("hint", "")),
            ttl_days=int(item.get("ttl_days", 90)),
            rubric=_parse_rubric(item.get("rubric")),
        )
        for item in raw.get("dimensions", [])
    )
    return AnalysisConfig(
        dimensions=dimensions,
        language=str(prompt_raw.get("language", "simple")),
        include_quant_summary=bool(prompt_raw.get("include_quant_summary", True)),
        require_rubric_alignment=bool(prompt_raw.get("require_rubric_alignment", True)),
    )


def _parse_rubric(raw: Any) -> dict[int, str]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {int(key): str(value) for key, value in raw.items()}
    return {}
