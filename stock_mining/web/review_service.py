from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from stock_mining.config import load_pipeline_config
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


@dataclass
class ReviewService:
    results_dir: Path
    state: UserStateStore
    dimensions_config: AnalysisConfig
    suppress_days: int = DEFAULT_SUPPRESS_DAYS
    too_expensive_drop_ratio: float = DEFAULT_TOO_EXPENSIVE_DROP_RATIO

    @classmethod
    def from_project_root(cls, root: Path) -> "ReviewService":
        config = load_pipeline_config(root / "config" / "screen.yaml")
        dimensions = load_dimensions_config(root / "config" / "analysis_dimensions.yaml")
        state_cfg = config.state
        suppress_days = getattr(state_cfg, "disposition_suppress_days", DEFAULT_SUPPRESS_DAYS)
        drop_ratio = getattr(
            state_cfg,
            "too_expensive_drop_ratio",
            DEFAULT_TOO_EXPENSIVE_DROP_RATIO,
        )
        return cls(
            results_dir=root / config.output.directory,
            state=UserStateStore(state_cfg.db_path),
            dimensions_config=dimensions,
            suppress_days=suppress_days,
            too_expensive_drop_ratio=drop_ratio,
        )

    def load_candidates(self) -> list[CandidateHit]:
        json_path = self.results_dir / "candidates.json"
        if not json_path.exists():
            return []
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return [CandidateHit.from_dict(item) for item in payload.get("candidates", [])]

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
