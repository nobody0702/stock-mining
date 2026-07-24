from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.bulk_not_interested_rules import (
    REASON_BJ,
    REASON_LOW_GM,
    REASON_ST,
    RuleHit,
    apply_hits,
    classify_st_or_bj,
    is_persistently_low_gross_margin,
)
from stock_mining.models import AnnualMetrics
from stock_mining.state.disposition import DispositionKind
from stock_mining.state.store import UserStateStore


def test_classify_st_or_bj():
    assert classify_st_or_bj("600519", "贵州茅台") is None
    assert classify_st_or_bj("000001", "*ST示例") == REASON_ST
    assert classify_st_or_bj("000001", "st退市整理") == REASON_ST
    assert classify_st_or_bj("920000", "某北交所") == REASON_BJ
    assert classify_st_or_bj("830001", "某新三板风格") == REASON_BJ
    assert classify_st_or_bj("430001", "某北证") == REASON_BJ
    # ST takes precedence over BJ when both could apply
    assert classify_st_or_bj("920000", "ST北交") == REASON_ST


def _annual(year: int, gm: float | None) -> AnnualMetrics:
    return AnnualMetrics(report_date=date(year, 12, 31), gross_margin_pct=gm)


def test_low_gross_margin_requires_three_years_all_below():
    ok = [_annual(2022, 10.0), _annual(2023, 15.0), _annual(2024, 19.9)]
    assert is_persistently_low_gross_margin(ok, years=3, max_pct=20.0) is True


def test_low_gross_margin_rejects_equal_threshold():
    rows = [_annual(2022, 10.0), _annual(2023, 15.0), _annual(2024, 20.0)]
    assert is_persistently_low_gross_margin(rows, years=3, max_pct=20.0) is False


def test_low_gross_margin_rejects_missing_year_or_none():
    two = [_annual(2023, 10.0), _annual(2024, 10.0)]
    assert is_persistently_low_gross_margin(two, years=3, max_pct=20.0) is False

    with_none = [_annual(2022, 10.0), _annual(2023, None), _annual(2024, 10.0)]
    assert is_persistently_low_gross_margin(with_none, years=3, max_pct=20.0) is False


def test_low_gross_margin_ignores_interim_reports():
    rows = [
        AnnualMetrics(report_date=date(2022, 6, 30), gross_margin_pct=5.0),
        _annual(2022, 10.0),
        _annual(2023, 11.0),
        _annual(2024, 12.0),
    ]
    assert is_persistently_low_gross_margin(rows, years=3, max_pct=20.0) is True


def test_apply_hits_skips_existing_unless_force(tmp_path: Path):
    store = UserStateStore(tmp_path / "state.sqlite3", dispositions_dir=tmp_path / "disp")
    store.set_stock_disposition(
        "a:600001",
        "已有自选",
        "a",
        DispositionKind.WATCHLIST,
    )
    hits = [
        RuleHit("600001", "已有自选", REASON_ST),
        RuleHit("600002", "新票", REASON_BJ),
    ]

    written, skipped = apply_hits(
        store, hits, suppress_days=365, force=False, dry_run=False
    )
    assert written == 1
    assert skipped == 1
    assert store.get_stock_disposition("a:600001").disposition == DispositionKind.WATCHLIST
    assert store.get_stock_disposition("a:600002").disposition == DispositionKind.NOT_INTERESTED

    written2, skipped2 = apply_hits(
        store, hits, suppress_days=365, force=True, dry_run=False
    )
    assert written2 == 2
    assert skipped2 == 0
    assert store.get_stock_disposition("a:600001").disposition == DispositionKind.NOT_INTERESTED


def test_apply_hits_dry_run_does_not_write(tmp_path: Path):
    store = UserStateStore(tmp_path / "state.sqlite3", dispositions_dir=tmp_path / "disp")
    hits = [RuleHit("600003", "干跑", REASON_LOW_GM)]
    written, skipped = apply_hits(
        store, hits, suppress_days=365, force=False, dry_run=True
    )
    assert written == 1
    assert skipped == 0
    assert store.get_stock_disposition("a:600003") is None
