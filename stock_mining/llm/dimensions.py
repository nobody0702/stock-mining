from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AnalysisDimension:
    id: str
    label: str
    hint: str
    ttl_days: int


@dataclass(frozen=True)
class AnalysisConfig:
    dimensions: tuple[AnalysisDimension, ...]
    language: str = "simple"
    include_quant_summary: bool = True


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
        )
        for item in raw.get("dimensions", [])
    )
    return AnalysisConfig(
        dimensions=dimensions,
        language=str(prompt_raw.get("language", "simple")),
        include_quant_summary=bool(prompt_raw.get("include_quant_summary", True)),
    )
