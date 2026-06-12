from datetime import date

from stock_mining.audit.verifier import audit_context
from stock_mining.filters.registry import build_filter
from stock_mining.models import (
    AnnualMetrics,
    MarketSnapshot,
    ScreeningContext,
    StockFinancials,
    StockInfo,
)


def test_audit_context_reports_failures():
    filters = [
        build_filter({"name": "non_st", "type": "non_st"}),
        build_filter(
            {
                "name": "margin_quality",
                "type": "margin_or_window",
                "years": 3,
                "gross_margin_min_pct": 40,
                "net_margin_min_pct": 20,
            }
        ),
    ]
    ctx = ScreeningContext(
        stock=StockInfo("000001", "ST测试"),
        financials=StockFinancials(
            "000001",
            [AnnualMetrics(date(2024, 12, 31), gross_margin_pct=50, net_margin_pct=25)],
        ),
    )
    report = audit_context(ctx, filters)
    assert not report.passed
    assert any(not row.passed for row in report.rows)
    assert any("可用年报" in note for note in report.data_notes)
