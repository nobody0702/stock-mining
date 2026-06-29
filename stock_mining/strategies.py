from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScreenStrategy:
    id: str
    label: str
    config_path: str
    candidates_json: str


STRATEGIES: dict[str, ScreenStrategy] = {
    "mispriced_growth": ScreenStrategy(
        id="mispriced_growth",
        label="错杀成长白马",
        config_path="config/screen.yaml",
        candidates_json="candidates.json",
    ),
    "normal_value": ScreenStrategy(
        id="normal_value",
        label="正常估值不下滑",
        config_path="config/screen_normal_value.yaml",
        candidates_json="normal_value_candidates.json",
    ),
    "normal_value_bm_pass": ScreenStrategy(
        id="normal_value_bm_pass",
        label="正常估值·商业模式≥4",
        config_path="config/screen_normal_value.yaml",
        candidates_json="normal_value_review.json",
    ),
    "mispriced_growth_hk": ScreenStrategy(
        id="mispriced_growth_hk",
        label="港股·错杀成长白马",
        config_path="config/screen_hk.yaml",
        candidates_json="hk_candidates.json",
    ),
}


def list_strategies() -> tuple[ScreenStrategy, ...]:
    return tuple(STRATEGIES.values())


def get_strategy(strategy_id: str) -> ScreenStrategy:
    if strategy_id not in STRATEGIES:
        known = ", ".join(STRATEGIES)
        raise ValueError(f"Unknown strategy {strategy_id!r}; choose from: {known}")
    return STRATEGIES[strategy_id]


def resolve_config_path(root: Path, strategy_id: str) -> Path:
    rel = get_strategy(strategy_id).config_path
    path = Path(rel)
    return path if path.is_absolute() else root / path


def resolve_candidates_json(root: Path, strategy_id: str) -> Path:
    strategy = get_strategy(strategy_id)
    return root / "data" / "results" / strategy.candidates_json
