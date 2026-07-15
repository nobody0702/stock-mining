from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stock_mining.config import load_pipeline_config, resolve_project_path
from stock_mining.llm.dimensions import AnalysisConfig, load_dimensions_config
from stock_mining.llm.prompt_builder import build_batch_prompt, build_stock_prompt
from stock_mining.llm.table_parser import missing_dimensions, parse_markdown_table
from stock_mining.models import CandidateHit
from stock_mining.state.disposition import (
    DEFAULT_SUPPRESS_DAYS,
    DEFAULT_TOO_EXPENSIVE_DROP_RATIO,
    DISPOSITION_LABELS,
    DispositionKind,
    StockDispositionEntry,
    too_expensive_reentry_price,
)
from stock_mining.state.store import UserStateStore
from stock_mining.strategies import ScreenStrategy, get_strategy, resolve_config_path


@dataclass
class CandidatesPayload:
    strategy_id: str
    json_path: Path
    candidates: list[CandidateHit]
    count: int
    top_n: int | None
    run_at: str | None
    source: str | None
    business_model_min_score: int | None
    mtime: datetime


@dataclass
class ReviewService:
    root: Path
    strategy: ScreenStrategy
    results_dir: Path
    state: UserStateStore
    dimensions_config: AnalysisConfig
    suppress_days: int = DEFAULT_SUPPRESS_DAYS
    too_expensive_drop_ratio: float = DEFAULT_TOO_EXPENSIVE_DROP_RATIO

    @classmethod
    def from_project_root(cls, root: Path, *, strategy_id: str = "mispriced_growth") -> "ReviewService":
        strategy = get_strategy(strategy_id)
        config_path = resolve_config_path(root, strategy.id)
        config = load_pipeline_config(config_path)
        dimensions = load_dimensions_config(root / "config" / "analysis_dimensions.yaml")
        state_cfg = config.state
        results_dir = resolve_project_path(config_path, config.output.directory)
        return cls(
            root=root,
            strategy=strategy,
            results_dir=results_dir,
            state=UserStateStore(
                resolve_project_path(config_path, state_cfg.db_path),
                dispositions_dir=resolve_project_path(config_path, state_cfg.dispositions_dir),
            ),
            dimensions_config=dimensions,
            suppress_days=state_cfg.disposition_suppress_days,
            too_expensive_drop_ratio=state_cfg.too_expensive_drop_ratio,
        )

    @property
    def strategy_id(self) -> str:
        return self.strategy.id

    @property
    def strategy_label(self) -> str:
        return self.strategy.label

    def candidates_json_path(self) -> Path:
        return self.results_dir / self.strategy.candidates_json

    def load_candidates_payload(self) -> CandidatesPayload | None:
        from stock_mining.pipeline.candidate_index import dedupe_candidates_by_stock_key

        json_path = self.candidates_json_path()
        if not json_path.exists():
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        candidates = [CandidateHit.from_dict(item) for item in payload.get("candidates", [])]
        # Defensive: old all_candidates.json may contain per-strategy duplicates.
        candidates = dedupe_candidates_by_stock_key(candidates)
        mtime = datetime.fromtimestamp(json_path.stat().st_mtime)
        return CandidatesPayload(
            strategy_id=str(payload.get("strategy", self.strategy.id)),
            json_path=json_path,
            candidates=candidates,
            count=len(candidates),
            top_n=payload.get("top_n"),
            run_at=payload.get("run_at") or payload.get("generated_at"),
            source=payload.get("source"),
            business_model_min_score=payload.get("business_model_min_score"),
            mtime=mtime,
        )

    def load_candidates(self) -> list[CandidateHit]:
        loaded = self.load_candidates_payload()
        return loaded.candidates if loaded else []

    def build_prompt(self, hit: CandidateHit) -> str:
        return build_stock_prompt(hit, self.dimensions_config)

    def build_batch_prompt(self, hits: list[CandidateHit]) -> str:
        return build_batch_prompt(hits, self.dimensions_config)

    def submit_analysis(
        self,
        hit: CandidateHit,
        markdown_text: str,
    ) -> tuple[list[int], list[str]]:
        parsed = parse_markdown_table(markdown_text, self.dimensions_config.dimensions)
        missing = missing_dimensions(parsed, self.dimensions_config.dimensions)
        entry_ids: list[int] = []
        ttl_map = {item.id: item.ttl_days for item in self.dimensions_config.dimensions}
        for dimension_id, content in parsed.items():
            entry_id = self.state.save_analysis_pending(
                hit.stock_key,
                hit.name,
                hit.market.value,
                dimension_id,
                content,
            )
            self.state.approve_analysis(entry_id, ttl_map.get(dimension_id, 90))
            entry_ids.append(entry_id)
        return entry_ids, missing

    def get_disposition(self, stock_key: str) -> StockDispositionEntry | None:
        return self.state.get_stock_disposition(stock_key)

    def get_disposition_kind(self, stock_key: str) -> str | None:
        entry = self.get_disposition(stock_key)
        return entry.disposition if entry else None

    def set_disposition(self, hit: CandidateHit, kind: str) -> None:
        if kind not in (
            DispositionKind.NOT_INTERESTED,
            DispositionKind.TOO_EXPENSIVE,
            DispositionKind.WATCHLIST,
        ):
            raise ValueError(f"Invalid disposition kind: {kind}")

        reference_price = None
        if kind == DispositionKind.TOO_EXPENSIVE:
            raw = hit.metrics.get("price")
            if raw is not None:
                try:
                    reference_price = float(raw)
                except (TypeError, ValueError):
                    reference_price = None

        self.state.set_stock_disposition(
            hit.stock_key,
            hit.name,
            hit.market.value,
            kind,
            reference_price=reference_price,
            suppress_days=self.suppress_days,
        )

    def remove_watchlist(self, stock_key: str) -> None:
        entry = self.get_disposition(stock_key)
        if entry is None or entry.disposition != DispositionKind.WATCHLIST:
            return
        self.state.clear_stock_disposition(stock_key)

    def list_dispositions(self, kind: str) -> list[StockDispositionEntry]:
        return self.state.list_stock_dispositions(disposition=kind, active_only=True)

    def disposition_label(self, kind: str) -> str:
        return DISPOSITION_LABELS.get(kind, kind)

    def too_expensive_threshold(self, reference_price: float) -> float:
        return too_expensive_reentry_price(
            reference_price,
            drop_ratio=self.too_expensive_drop_ratio,
        )

    def get_cached_analysis_table(self, hit: CandidateHit) -> dict[str, str]:
        table: dict[str, str] = {}
        for dimension in self.dimensions_config.dimensions:
            entry = self.state.get_valid_analysis(hit.stock_key, dimension.id)
            if entry is not None:
                table[dimension.label] = entry.content
        return table

    def release_expired_dispositions(self) -> int:
        return self.state.release_expired_dispositions()


def pick_latest_strategy_id(root: Path) -> str:
    """Prefer the screen result JSON most recently written."""
    from stock_mining.strategies import STRATEGIES

    latest_id = "mispriced_growth"
    latest_mtime: float | None = None
    for strategy in STRATEGIES.values():
        config_path = resolve_config_path(root, strategy.id)
        config = load_pipeline_config(config_path)
        results_dir = resolve_project_path(config_path, config.output.directory)
        json_path = results_dir / strategy.candidates_json
        if not json_path.exists():
            continue
        mtime = json_path.stat().st_mtime
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_id = strategy.id
    return latest_id
