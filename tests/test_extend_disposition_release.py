from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.extend_disposition_release import extend_release_at


def test_extend_release_at_sets_days_after_set_at(tmp_path: Path):
    dispositions_dir = tmp_path / "dispositions"
    dispositions_dir.mkdir()
    set_at = "2026-01-01T10:00:00"
    (dispositions_dir / "not_interested.json").write_text(
        json.dumps(
            [
                {
                    "stock_key": "a:600519",
                    "name": "茅台",
                    "market": "a",
                    "reference_price": None,
                    "set_at": set_at,
                    "release_at": "2026-04-01T10:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (dispositions_dir / "watchlist.json").write_text("[]\n", encoding="utf-8")

    updated = extend_release_at(dispositions_dir, days_after_set_at=365)
    assert updated == 1

    payload = json.loads((dispositions_dir / "not_interested.json").read_text(encoding="utf-8"))
    release_at = datetime.fromisoformat(payload[0]["release_at"])
    expected = datetime.fromisoformat(set_at).replace(year=2027)
    assert release_at == expected


def test_review_service_default_suppress_days_is_half_year():
    from stock_mining.config import load_pipeline_config
    from stock_mining.state.disposition import SUPPRESS_DAYS_HALF_YEAR
    from stock_mining.web.review_service import ReviewService

    root = Path(__file__).resolve().parents[1]
    service = ReviewService.from_project_root(root, strategy_id="mispriced_growth")
    assert service.suppress_days == SUPPRESS_DAYS_HALF_YEAR
    cfg = load_pipeline_config(root / "config" / "screen.yaml")
    assert cfg.state.disposition_suppress_days == SUPPRESS_DAYS_HALF_YEAR
