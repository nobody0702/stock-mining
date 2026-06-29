from __future__ import annotations

import json
from pathlib import Path

from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.state.store import UserStateStore
from stock_mining.strategies import get_strategy
from stock_mining.web.review_service import ReviewService


def test_load_candidates_uses_strategy_json(tmp_path):
    root = Path(__file__).resolve().parents[1]
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    hit = {
        "code": "600007",
        "name": "中国国贸",
        "market": "a",
        "track": "normal_valuation_stable",
        "score": 80.0,
        "metrics": {},
    }
    (results_dir / "normal_value_candidates.json").write_text(
        json.dumps({"candidates": [hit], "count": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    (results_dir / "candidates.json").write_text(
        json.dumps({"candidates": [], "count": 0}, ensure_ascii=False),
        encoding="utf-8",
    )

    from stock_mining.llm.dimensions import load_dimensions_config
    from stock_mining.state.store import UserStateStore

    service = ReviewService(
        root=root,
        strategy=get_strategy("normal_value"),
        results_dir=results_dir,
        state=UserStateStore(tmp_path / "state.sqlite3"),
        dimensions_config=load_dimensions_config(root / "config" / "analysis_dimensions.yaml"),
    )
    loaded = service.load_candidates()
    assert len(loaded) == 1
    assert loaded[0].code == "600007"
    assert service.candidates_json_path().name == "normal_value_candidates.json"
