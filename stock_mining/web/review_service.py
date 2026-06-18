from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stock_mining.config import load_pipeline_config
from stock_mining.llm.dimensions import AnalysisConfig, load_dimensions_config
from stock_mining.llm.prompt_builder import build_batch_prompt, build_stock_prompt
from stock_mining.llm.table_parser import missing_dimensions, parse_markdown_table
from stock_mining.models import CandidateHit
from stock_mining.state.store import UserStateStore


@dataclass
class ReviewService:
    results_dir: Path
    state: UserStateStore
    dimensions_config: AnalysisConfig
    blacklist_release_days: int = 180
    recommendation_cooldown_days: int = 30

    @classmethod
    def from_project_root(cls, root: Path) -> "ReviewService":
        config = load_pipeline_config(root / "config" / "screen.yaml")
        dimensions = load_dimensions_config(root / "config" / "analysis_dimensions.yaml")
        return cls(
            results_dir=root / config.output.directory,
            state=UserStateStore(config.state.db_path),
            dimensions_config=dimensions,
            blacklist_release_days=config.state.blacklist_release_days,
            recommendation_cooldown_days=config.state.recommendation_cooldown_days,
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
        for dimension_id, content in parsed.items():
            entry_id = self.state.save_analysis_pending(
                hit.stock_key,
                hit.name,
                hit.market.value,
                dimension_id,
                content,
            )
            entry_ids.append(entry_id)
        return entry_ids, missing

    def approve_analysis_entries(self, entry_ids: list[int]) -> None:
        ttl_map = {item.id: item.ttl_days for item in self.dimensions_config.dimensions}
        for entry in self.state.list_pending_analysis():
            if entry.id not in entry_ids:
                continue
            ttl_days = ttl_map.get(entry.dimension_id, 90)
            self.state.approve_analysis(entry.id, ttl_days)

    def reject_analysis_entries(self, entry_ids: list[int]) -> None:
        for entry_id in entry_ids:
            self.state.reject_analysis(entry_id)

    def add_blacklist(self, hit: CandidateHit, reason: str) -> int:
        entry_id = self.state.add_blacklist_pending(
            hit.stock_key,
            hit.name,
            hit.market.value,
            reason,
            self.blacklist_release_days,
        )
        self.state.approve_blacklist(entry_id)
        return entry_id

    def mark_studied(self, hit: CandidateHit) -> int:
        return self.state.mark_studied(
            hit.stock_key,
            hit.name,
            hit.market.value,
            self.recommendation_cooldown_days,
        )

    def get_cached_analysis_table(self, hit: CandidateHit) -> dict[str, str]:
        table: dict[str, str] = {}
        for dimension in self.dimensions_config.dimensions:
            entry = self.state.get_valid_analysis(hit.stock_key, dimension.id)
            if entry is not None:
                table[dimension.label] = entry.content
        return table

    def release_expired_blacklist(self) -> int:
        return self.state.release_expired_blacklist()

    def pending_analysis(self):
        return self.state.list_pending_analysis()

    def blacklist_entries(self):
        return self.state.list_blacklist()

    def recommendation_entries(self):
        return self.state.list_recommendations()
