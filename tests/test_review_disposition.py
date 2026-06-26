from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from stock_mining.llm.dimensions import load_dimensions_config
from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit
from stock_mining.state.disposition import DispositionKind
from stock_mining.state.store import UserStateStore
from stock_mining.web.review_service import ReviewService


@pytest.fixture
def root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def service(tmp_path, root) -> ReviewService:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return ReviewService(
        results_dir=results_dir,
        state=UserStateStore(tmp_path / "state.sqlite3"),
        dimensions_config=load_dimensions_config(root / "config" / "analysis_dimensions.yaml"),
        suppress_days=90,
        too_expensive_drop_ratio=0.10,
    )


def _hit(code: str = "688001", *, price: float = 100.0) -> CandidateHit:
    return CandidateHit(
        code=code,
        name="样本",
        market=Market.A,
        track="profitable_growth",
        score=80,
        metrics={"price": price},
    )


def test_set_and_switch_disposition(service):
    hit = _hit()
    service.set_disposition(hit, DispositionKind.WATCHLIST)
    assert service.get_disposition_kind(hit.stock_key) == DispositionKind.WATCHLIST
    assert len(service.list_dispositions(DispositionKind.WATCHLIST)) == 1

    service.set_disposition(hit, DispositionKind.NOT_INTERESTED)
    assert service.get_disposition_kind(hit.stock_key) == DispositionKind.NOT_INTERESTED
    assert service.list_dispositions(DispositionKind.WATCHLIST) == []
    assert len(service.list_dispositions(DispositionKind.NOT_INTERESTED)) == 1


def test_too_expensive_captures_price(service):
    hit = _hit(price=123.45)
    service.set_disposition(hit, DispositionKind.TOO_EXPENSIVE)
    entry = service.get_disposition(hit.stock_key)
    assert entry is not None
    assert entry.reference_price == 123.45
    assert service.too_expensive_threshold(123.45) == pytest.approx(111.105)


def test_remove_watchlist_only(service):
    hit = _hit()
    service.set_disposition(hit, DispositionKind.NOT_INTERESTED)
    service.remove_watchlist(hit.stock_key)
    assert service.get_disposition_kind(hit.stock_key) == DispositionKind.NOT_INTERESTED

    service.set_disposition(hit, DispositionKind.WATCHLIST)
    service.remove_watchlist(hit.stock_key)
    assert service.get_disposition_kind(hit.stock_key) is None


def test_submit_analysis_auto_approves(service):
    hit = _hit()
    markdown = """
| 维度 | 内容 |
| --- | --- |
| 商业模式（1-5分） | 4分，靠卖软件订阅赚钱 |
| 护城河（1-5分） | 3分，有一定客户粘性 |
| 成长性（1-5分） | 3分，行业仍有空间 |
| 管理层（1-5分） | 4分，团队较稳定 |
| 企业文化（1-5分） | 3分，总体守规矩 |
| 安全边际（1-5分） | 4分，PE 显示约 30% 折扣 |
"""
    entry_ids, missing = service.submit_analysis(hit, markdown)
    assert entry_ids
    assert not missing
    cached = service.get_cached_analysis_table(hit)
    assert "护城河（1-5分）" in cached


def test_load_candidates_from_json(service):
    hit = _hit()
    payload = {
        "candidates": [hit.to_dict()],
        "generated_at": datetime.now().isoformat(),
    }
    (service.results_dir / "candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    loaded = service.load_candidates()
    assert len(loaded) == 1
    assert loaded[0].stock_key == hit.stock_key
