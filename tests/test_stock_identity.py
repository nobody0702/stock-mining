from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from stock_mining.llm.business_model_results import load_business_model_scores, parse_batch_markdown
from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit
from stock_mining.pipeline.candidate_index import index_by_code, lookup_by_code, lookup_by_stock_key


def _hit(code: str, name: str) -> CandidateHit:
    return CandidateHit(
        code=code,
        name=name,
        market=Market.A,
        track="normal_valuation_stable",
        score=80.0,
    )


def test_lookup_by_code_ignores_name_change():
    hits = [_hit("600007", "中国国贸")]
    row = parse_batch_markdown(
        "| 代码 | 名称 | 商业模式打分 | 商业模式简单描述 | 扣分理由 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 600007 | XD中国国 | 4 | 收租 | 波动 |\n"
    )[0]
    hit = lookup_by_code(hits, row.code)
    assert hit is not None
    assert hit.code == "600007"
    assert hit.name == "中国国贸"
    assert row.name == "XD中国国"


def test_index_by_code_does_not_use_name():
    hits = [
        _hit("600007", "中国国贸"),
        _hit("600750", "华润江中"),
    ]
    indexed = index_by_code(hits)
    assert set(indexed) == {"600007", "600750"}
    assert lookup_by_code(hits, "600007") is hits[0]


def test_lookup_by_stock_key_stable_when_name_changes():
    original = _hit("600007", "中国国贸")
    renamed = _hit("600007", "XD中国国")
    hits = [original]
    assert lookup_by_stock_key(hits, renamed.stock_key) is original


def test_load_business_model_scores_keys_by_code(tmp_path: Path):
    (tmp_path / "batch_01.md").write_text(
        "| 代码 | 名称 | 商业模式打分 | 商业模式简单描述 | 扣分理由 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 600007 | XD中国国 | 4 | 收租 | 波动 |\n",
        encoding="utf-8",
    )
    scores = load_business_model_scores(tmp_path)
    assert list(scores) == ["600007"]
    assert scores["600007"].score == 4


def test_triage_join_prefers_code_over_name(tmp_path: Path):
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.state.store import UserStateStore

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "batch_01.md").write_text(
        "| 代码 | 名称 | 商业模式打分 | 商业模式简单描述 | 扣分理由 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 600007 | XD中国国 | 2 | 收租 | 扣分 |\n"
        "| 600750 | 江中制药 | 4 | 卖药 | 无 |\n",
        encoding="utf-8",
    )

    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(
        '{"candidates": ['
        '{"code":"600007","name":"中国国贸","market":"a","track":"t","score":1.0,"metrics":{}},'
        '{"code":"600750","name":"华润江中","market":"a","track":"t","score":2.0,"metrics":{}}'
        "]}",
        encoding="utf-8",
    )

    from stock_mining.llm.business_model_batch import load_candidates

    scores = load_business_model_scores(results_dir)
    hits = load_candidates(candidates_path)
    now = datetime(2026, 6, 19, 12, 0, 0)
    release_at = now + timedelta(days=183)
    store = UserStateStore(tmp_path / "state.sqlite3", dispositions_dir=tmp_path / "dispositions")

    for code, row in scores.items():
        hit = lookup_by_code(hits, code)
        assert hit is not None, code
        if row.score < 4:
            store.set_stock_disposition(
                hit.stock_key,
                row.name,
                hit.market.value,
                DispositionKind.NOT_INTERESTED,
                release_at=release_at,
                now=now,
            )

    not_interested = store.list_stock_dispositions(disposition=DispositionKind.NOT_INTERESTED)
    assert len(not_interested) == 1
    assert not_interested[0].stock_key == "a:600007"
    assert not_interested[0].name == "XD中国国"
    assert not_interested[0].release_at == release_at

    pass_hits = [lookup_by_code(hits, code) for code, row in scores.items() if row.score >= 4]
    assert len(pass_hits) == 1
    assert pass_hits[0].code == "600750"
