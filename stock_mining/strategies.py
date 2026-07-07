from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stock_mining.markets.base import Market


@dataclass(frozen=True)
class ScreenStrategy:
    id: str
    label: str
    config_path: str
    candidates_json: str
    markets: tuple[Market, ...] = (Market.A,)


MINING_STRATEGIES: dict[str, ScreenStrategy] = {
    "mispriced_growth": ScreenStrategy(
        id="mispriced_growth",
        label="被错杀的白马股",
        config_path="config/screen.yaml",
        candidates_json="candidates.json",
        markets=(Market.A,),
    ),
    "normal_value": ScreenStrategy(
        id="normal_value",
        label="正常估值不下滑",
        config_path="config/screen_normal_value.yaml",
        candidates_json="normal_value_candidates.json",
        markets=(Market.A,),
    ),
    "mispriced_growth_hk": ScreenStrategy(
        id="mispriced_growth_hk",
        label="港股·被错杀的白马股",
        config_path="config/screen_hk.yaml",
        candidates_json="hk_candidates.json",
        markets=(Market.HK,),
    ),
    "quality_roe_margin": ScreenStrategy(
        id="quality_roe_margin",
        label="连续高ROE高毛利",
        config_path="config/screen_quality_roe_margin.yaml",
        candidates_json="quality_roe_margin_candidates.json",
        markets=(Market.A,),
    ),
}

REVIEW_STRATEGIES: dict[str, ScreenStrategy] = {
    **MINING_STRATEGIES,
    "normal_value_bm_pass": ScreenStrategy(
        id="normal_value_bm_pass",
        label="正常估值·商业模式≥4",
        config_path="config/screen_normal_value.yaml",
        candidates_json="normal_value_review.json",
        markets=(Market.A,),
    ),
    "all": ScreenStrategy(
        id="all",
        label="所有策略合并",
        config_path="config/screen.yaml",
        candidates_json="all_candidates.json",
        markets=(Market.A, Market.HK),
    ),
}

STRATEGIES = REVIEW_STRATEGIES


def list_strategies(*, mining_only: bool = False) -> tuple[ScreenStrategy, ...]:
    source = MINING_STRATEGIES if mining_only else REVIEW_STRATEGIES
    return tuple(source.values())


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


def parse_strategy_selection(value: str) -> list[str]:
    """Parse strategy id(s); supports comma-separated list and ``all``."""
    raw = value.strip()
    if not raw:
        raise ValueError("strategy selection must not be empty")

    if "," not in raw:
        return mining_jobs_for(raw)

    selected: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        token = part.strip().lower()
        if not token:
            continue
        for job_id in mining_jobs_for(token):
            if job_id not in seen:
                selected.append(job_id)
                seen.add(job_id)
    if not selected:
        raise ValueError(f"No mining strategies in {value!r}")
    return selected


def mining_jobs_for(strategy_id: str) -> list[str]:
    """Return mining strategy ids to run (expands ``all``)."""
    token = strategy_id.strip().lower()
    if token == "all":
        return list(MINING_STRATEGIES.keys())
    if token in MINING_STRATEGIES:
        return [token]
    known = ", ".join(MINING_STRATEGIES) + ", all"
    raise ValueError(f"Not a mining strategy: {strategy_id!r}; choose from: {known}")