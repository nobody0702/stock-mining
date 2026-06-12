from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from stock_mining.utils import normalize_code


@dataclass
class UniverseConfig:
    exclude_st: bool = True
    exclude_bj: bool = True
    max_stocks: int | None = None
    codes: list[str] | None = None


@dataclass
class FetchConfig:
    use_cache: bool = True
    cache_dir: str = "data/cache"
    cache_ttl_hours: int = 12
    financial_workers: int = 4
    request_interval_sec: float = 0.15


@dataclass
class OutputConfig:
    directory: str = "data/results"
    filename: str = "daily_screen.csv"


@dataclass
class PipelineConfig:
    data_source: str
    universe: UniverseConfig
    filters: list[dict[str, Any]]
    fetch: FetchConfig
    output: OutputConfig


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)

    universe_raw = raw.get("universe", {})
    fetch_raw = raw.get("fetch", {})
    output_raw = raw.get("output", {})

    codes = universe_raw.get("codes")
    if codes:
        codes = [normalize_code(code) for code in codes]

    return PipelineConfig(
        data_source=raw.get("data_source", "akshare"),
        universe=UniverseConfig(
            exclude_st=bool(universe_raw.get("exclude_st", True)),
            exclude_bj=bool(universe_raw.get("exclude_bj", True)),
            max_stocks=universe_raw.get("max_stocks"),
            codes=codes,
        ),
        filters=list(raw.get("filters", [])),
        fetch=FetchConfig(
            use_cache=bool(fetch_raw.get("use_cache", True)),
            cache_dir=str(fetch_raw.get("cache_dir", "data/cache")),
            cache_ttl_hours=int(fetch_raw.get("cache_ttl_hours", 12)),
            financial_workers=int(fetch_raw.get("financial_workers", 4)),
            request_interval_sec=float(fetch_raw.get("request_interval_sec", 0.15)),
        ),
        output=OutputConfig(
            directory=str(output_raw.get("directory", "data/results")),
            filename=str(output_raw.get("filename", "daily_screen.csv")),
        ),
    )
