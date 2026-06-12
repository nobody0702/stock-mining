from __future__ import annotations

from dataclasses import dataclass

from stock_mining.filters.base import Filter
from stock_mining.models import ScreeningContext


@dataclass(frozen=True)
class FilterAuditRow:
    filter_name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class StockAuditReport:
    code: str
    name: str
    passed: bool
    rows: tuple[FilterAuditRow, ...]
    data_notes: tuple[str, ...] = ()


def audit_context(
    ctx: ScreeningContext,
    filters: list[Filter],
) -> StockAuditReport:
    rows: list[FilterAuditRow] = []
    notes: list[str] = []
    for filter_ in filters:
        result = filter_.evaluate(ctx)
        rows.append(
            FilterAuditRow(
                filter_name=filter_.name,
                passed=result.passed,
                reason=result.reason,
            )
        )

    notes.extend(_collect_data_notes(ctx))
    passed = all(row.passed for row in rows)
    stock = ctx.stock
    return StockAuditReport(
        code=stock.code,
        name=stock.name,
        passed=passed,
        rows=tuple(rows),
        data_notes=tuple(notes),
    )


def _collect_data_notes(ctx: ScreeningContext) -> list[str]:
    notes: list[str] = []
    financials = ctx.financials
    if financials is None:
        notes.append("财务数据: 缺失")
        return notes

    annual = [
        item
        for item in financials.annual
        if item.report_date.month == 12 and item.report_date.day == 31
    ]
    annual.sort(key=lambda item: item.report_date)
    notes.append(f"财务数据: 可用年报 {len(annual)} 期")
    if annual:
        years = [item.report_date.year for item in annual[-3:]]
        notes.append(f"最近3个年报年度: {years}")

    market = ctx.market
    if market is None:
        notes.append("行情快照: 缺失")
    else:
        missing = [
            name
            for name, value in {
                "price": market.price,
                "low_52w": market.low_52w,
                "pe": market.pe,
                "pb": market.pb,
                "ps": market.ps,
                "dividend_yield_pct": market.dividend_yield_pct,
                "industry": market.industry,
            }.items()
            if value is None
        ]
        if missing:
            notes.append(f"行情缺失字段: {', '.join(missing)}")
    return notes
