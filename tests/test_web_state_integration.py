from __future__ import annotations

from pathlib import Path

from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.state.store import UserStateStore
from stock_mining.strategies import get_strategy
from stock_mining.web.review_service import ReviewService


def test_review_service_load_empty_candidates(tmp_path):
    root = Path(__file__).resolve().parents[1]
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    service = ReviewService(
        root=root,
        strategy=get_strategy("mispriced_growth"),
        results_dir=results_dir,
        state=UserStateStore(tmp_path / "state.sqlite3"),
        dimensions_config=load_dimensions_config(root / "config" / "analysis_dimensions.yaml"),
    )
    assert service.load_candidates() == []
