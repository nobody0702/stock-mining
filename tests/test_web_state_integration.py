from __future__ import annotations

from pathlib import Path

from stock_mining.web.review_service import ReviewService


def test_review_service_load_empty_candidates(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    service = ReviewService(
        results_dir=results_dir,
        state=__import__("stock_mining.state.store", fromlist=["UserStateStore"]).UserStateStore(
            tmp_path / "state.sqlite3"
        ),
        dimensions_config=__import__(
            "stock_mining.llm.dimensions",
            fromlist=["load_dimensions_config"],
        ).load_dimensions_config(
            Path(__file__).resolve().parents[1] / "config" / "analysis_dimensions.yaml"
        ),
    )
    assert service.load_candidates() == []
