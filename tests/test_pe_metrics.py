import pytest

from stock_mining.markets.pe_metrics import (
    merge_pe_fields,
    parse_pe_from_spot_row,
    parse_pe_from_value_em_row,
    resolve_primary_pe,
)


def test_resolve_primary_pe_prefers_ttm_then_dynamic_then_static():
    assert resolve_primary_pe(pe_ttm=20.0, pe_dynamic=30.0, pe_static=25.0) == pytest.approx(20.0)
    assert resolve_primary_pe(pe_dynamic=30.0, pe_static=25.0) == pytest.approx(30.0)
    assert resolve_primary_pe(pe_static=25.0) == pytest.approx(25.0)
    assert resolve_primary_pe(fallback=12.0) == pytest.approx(12.0)


def test_parse_pe_from_value_em_row():
    row = {"PE(TTM)": 28.5, "PE(静)": 31.2}
    parsed = parse_pe_from_value_em_row(row)
    assert parsed["pe_ttm"] == pytest.approx(28.5)
    assert parsed["pe_static"] == pytest.approx(31.2)


def test_parse_pe_from_spot_row():
    row = {"市盈率-动态": 40.0}
    parsed = parse_pe_from_spot_row(row)
    assert parsed["pe_dynamic"] == pytest.approx(40.0)
    assert parsed["pe"] == pytest.approx(40.0)


def test_merge_pe_fields_sets_primary_pe():
    merged = merge_pe_fields(pe_ttm=15.0, pe_static=18.0, pe_dynamic=20.0)
    assert merged["pe"] == pytest.approx(15.0)
    assert merged["pe_dynamic"] == pytest.approx(20.0)
