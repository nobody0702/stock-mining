from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from stock_mining.markets.base import Market, normalize_stock_code
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
    snapshot_workers: int = 8
    request_interval_sec: float = 0.15


@dataclass
class ScoringConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "cheap": 0.5,
            "stability": 0.5,
        }
    )


@dataclass
class OutputConfig:
    directory: str = "data/results"
    filename: str = "daily_screen.csv"
    candidates_json: str = "candidates.json"
    candidates_csv: str = "candidates.csv"
    top_n: int | None = None


@dataclass
class StateConfig:
    db_path: str = "data/state/user_state.sqlite3"
    blacklist_release_days: int = 180
    recommendation_cooldown_days: int = 30
    disposition_suppress_days: int = 90
    too_expensive_drop_ratio: float = 0.10
    dispositions_dir: str = "data/state/dispositions"


@dataclass
class TrackConfig:
    name: str
    filters: list[dict[str, Any]]


@dataclass
class PipelineConfig:
    data_source: str
    markets: list[Market]
    universe: UniverseConfig
    common_filters: list[dict[str, Any]]
    tracks: list[TrackConfig]
    fetch: FetchConfig
    output: OutputConfig
    scoring: ScoringConfig
    state: StateConfig
    filters: list[dict[str, Any]] = field(default_factory=list)


def _parse_markets(raw: list[str] | None) -> list[Market]:
    if not raw:
        return [Market.A]
    return [Market(item) for item in raw]


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)

    universe_raw = raw.get("universe", {})
    fetch_raw = raw.get("fetch", {})
    output_raw = raw.get("output", {})
    scoring_raw = raw.get("scoring", {})
    state_raw = raw.get("state", {})

    codes = universe_raw.get("codes")
    if codes:
        codes = [normalize_code(code) for code in codes]

    tracks: list[TrackConfig] = []
    tracks_raw = raw.get("tracks", {})
    if isinstance(tracks_raw, dict):
        for name, track_body in tracks_raw.items():
            filters = track_body.get("filters", []) if isinstance(track_body, dict) else track_body
            tracks.append(TrackConfig(name=name, filters=list(filters or [])))
    elif isinstance(tracks_raw, list):
        for item in tracks_raw:
            tracks.append(
                TrackConfig(name=str(item["name"]), filters=list(item.get("filters", [])))
            )

    legacy_filters = list(raw.get("filters", []))
    common_filters = list(raw.get("common_filters", legacy_filters))

    return PipelineConfig(
        data_source=raw.get("data_source", "akshare"),
        markets=_parse_markets(raw.get("markets")),
        universe=UniverseConfig(
            exclude_st=bool(universe_raw.get("exclude_st", True)),
            exclude_bj=bool(universe_raw.get("exclude_bj", True)),
            max_stocks=universe_raw.get("max_stocks"),
            codes=codes,
        ),
        common_filters=common_filters,
        tracks=tracks,
        filters=legacy_filters,
        fetch=FetchConfig(
            use_cache=bool(fetch_raw.get("use_cache", True)),
            cache_dir=str(fetch_raw.get("cache_dir", "data/cache")),
            cache_ttl_hours=int(fetch_raw.get("cache_ttl_hours", 12)),
            financial_workers=int(fetch_raw.get("financial_workers", 4)),
            snapshot_workers=int(fetch_raw.get("snapshot_workers", 8)),
            request_interval_sec=float(fetch_raw.get("request_interval_sec", 0.15)),
        ),
        output=OutputConfig(
            directory=str(output_raw.get("directory", "data/results")),
            filename=str(output_raw.get("filename", "daily_screen.csv")),
            candidates_json=str(output_raw.get("candidates_json", "candidates.json")),
            candidates_csv=str(output_raw.get("candidates_csv", "candidates.csv")),
            top_n=(
                None
                if output_raw.get("top_n") is None
                else int(output_raw.get("top_n", 15))
            ),
        ),
        scoring=ScoringConfig(weights=dict(scoring_raw.get("weights", ScoringConfig().weights))),
        state=StateConfig(
            db_path=str(state_raw.get("db_path", "data/state/user_state.sqlite3")),
            blacklist_release_days=int(state_raw.get("blacklist_release_days", 180)),
            recommendation_cooldown_days=int(state_raw.get("recommendation_cooldown_days", 30)),
            disposition_suppress_days=int(state_raw.get("disposition_suppress_days", 90)),
            too_expensive_drop_ratio=float(state_raw.get("too_expensive_drop_ratio", 0.10)),
            dispositions_dir=str(state_raw.get("dispositions_dir", "data/state/dispositions")),
        ),
    )


def project_root_from_config(config_path: str | Path) -> Path:
    """Project root when config lives under `<root>/config/`."""
    return Path(config_path).resolve().parent.parent


def resolve_project_path(config_path: str | Path, relative: str | Path) -> Path:
    return project_root_from_config(config_path) / relative


def normalize_code_for_market(code: str, market: Market) -> str:
    return normalize_stock_code(code, market)

