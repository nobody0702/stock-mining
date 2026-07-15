from __future__ import annotations

import json
from pathlib import Path

from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit
from stock_mining.pipeline.candidate_index import dedupe_candidates_by_stock_key
from stock_mining.pipeline.multi_screen import ScreenRunResult, _write_merged_all_candidates
from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.state.store import UserStateStore
from stock_mining.strategies import get_strategy
from stock_mining.web.review_service import ReviewService


ROOT = Path(__file__).resolve().parents[1]


def _hit(
    code: str,
    *,
    name: str = "样本",
    track: str = "profitable_growth",
    score: float = 80.0,
    strategy: str | None = None,
) -> CandidateHit:
    metrics = {"price": 10.0}
    if strategy:
        metrics["source_strategy"] = strategy
    return CandidateHit(
        code=code,
        name=name,
        market=Market.A,
        track=track,
        score=score,
        metrics=metrics,
    )


def test_dedupe_candidates_keeps_highest_score_and_merges_sources():
    hits = [
        _hit("301327", name="华宝新能", track="loss_tolerant_growth", score=70.4, strategy="mispriced_growth"),
        _hit("301327", name="华宝新能", track="normal_valuation_stable", score=65.0, strategy="normal_value"),
        _hit("301327", name="华宝新能", track="loss_tolerant_growth", score=70.4, strategy="mispriced_growth"),
        _hit("600598", name="北大荒", track="profitable_growth", score=81.8, strategy="mispriced_growth"),
    ]
    out = dedupe_candidates_by_stock_key(hits)
    assert len(out) == 2
    by_key = {h.stock_key: h for h in out}
    assert by_key["a:301327"].score == 70.4
    assert by_key["a:301327"].track == "loss_tolerant_growth"
    assert by_key["a:301327"].metrics["source_strategies"] == [
        "mispriced_growth",
        "normal_value",
    ]
    assert "normal_valuation_stable" in by_key["a:301327"].metrics["matched_tracks"]
    assert by_key["a:600598"].name == "北大荒"


def test_write_merged_all_candidates_dedupes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "results").mkdir(parents=True)

    results = [
        ScreenRunResult(
            strategy_id="mispriced_growth",
            strategy_label="被错杀的白马股",
            markets=[Market.A],
            hits=[_hit("301327", name="华宝新能", score=70.4, strategy="mispriced_growth")],
            json_path=tmp_path / "a.json",
            csv_path=tmp_path / "a.csv",
            legacy_path=tmp_path / "a_legacy.csv",
        ),
        ScreenRunResult(
            strategy_id="normal_value",
            strategy_label="正常估值不下滑",
            markets=[Market.A],
            hits=[
                _hit(
                    "301327",
                    name="华宝新能",
                    track="normal_valuation_stable",
                    score=60.0,
                    strategy="normal_value",
                )
            ],
            json_path=tmp_path / "b.json",
            csv_path=tmp_path / "b.csv",
            legacy_path=tmp_path / "b_legacy.csv",
        ),
    ]
    path = _write_merged_all_candidates(tmp_path, results)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["stock_key"] == "a:301327"
    assert payload["candidates"][0]["metrics"]["source_strategies"] == [
        "mispriced_growth",
        "normal_value",
    ]


def test_review_service_load_dedupes_legacy_all_json(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    payload = {
        "strategy": "all",
        "candidates": [
            _hit("301327", name="华宝新能", score=70.4, strategy="mispriced_growth").to_dict(),
            _hit(
                "301327",
                name="华宝新能",
                track="normal_valuation_stable",
                score=50.0,
                strategy="normal_value",
            ).to_dict(),
            _hit("301327", name="华宝新能", score=70.4, strategy="mispriced_growth").to_dict(),
        ],
        "count": 3,
    }
    (results_dir / "all_candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    service = ReviewService(
        root=ROOT,
        strategy=get_strategy("all"),
        results_dir=results_dir,
        state=UserStateStore(tmp_path / "state.sqlite3"),
        dimensions_config=load_dimensions_config(ROOT / "config" / "analysis_dimensions.yaml"),
    )
    loaded = service.load_candidates()
    assert len(loaded) == 1
    assert loaded[0].stock_key == "a:301327"
    assert loaded[0].score == 70.4


def test_review_app_copy_iframes_are_fragment_isolated():
    """Copy iframes stay on per-card fragments; disposition must not force extra reruns."""
    import ast

    text = (ROOT / "stock_mining" / "web" / "review_app.py").read_text(encoding="utf-8")
    assert "@st.fragment" in text
    assert "def _candidate_card" in text
    assert "build_copy_prompt_html" in text

    tree = ast.parse(text)
    disp_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_disposition_selector"
    )
    # Extra st.rerun(scope="fragment") races Streamlit fragment lifecycle and
    # surfaces: "The fragment with id ... does not exist anymore".
    calls = [
        n
        for n in ast.walk(disp_fn)
        if isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Attribute) and n.func.attr == "rerun")
            or (isinstance(n.func, ast.Name) and n.func.id == "rerun")
        )
    ]
    assert calls == []
