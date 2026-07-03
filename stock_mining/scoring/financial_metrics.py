from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

from stock_mining.models import AnnualMetrics, StockFinancials
from stock_mining.utils import adaptive_annual_window

CashflowQuality = Literal[
    "missing_data",
    "both_weak",
    "profit_no_ocf",
    "ocf_covers_profit",
    "ocf_below_profit",
    "loss_positive_ocf",
]

OCF_COVERS_PROFIT_MIN_RATIO = 0.8


def is_annual_report(report_date: date) -> bool:
    return report_date.month == 12 and report_date.day == 31


def report_period_label(report_date: date) -> str:
    if is_annual_report(report_date):
        return f"{report_date.year}年报"
    if report_date.month == 3:
        return f"{report_date.year}一季报"
    if report_date.month == 6:
        return f"{report_date.year}半年报"
    if report_date.month == 9:
        return f"{report_date.year}三季报"
    return report_date.isoformat()


def _sorted_periods(financials: StockFinancials, *, today: date | None = None) -> list[AnnualMetrics]:
    as_of = today or date.today()
    return sorted(
        (item for item in financials.annual if item.report_date <= as_of),
        key=lambda item: item.report_date,
    )


def _period_snapshot(item: AnnualMetrics) -> dict[str, Any]:
    return {
        "report_date": item.report_date.isoformat(),
        "period_label": report_period_label(item.report_date),
        "revenue_yuan": item.revenue_yuan,
        "net_profit_yuan": item.net_profit_yuan,
        "gross_margin_pct": item.gross_margin_pct,
        "net_margin_pct": item.net_margin_pct,
        "operating_cashflow_yuan": item.operating_cashflow_yuan,
        "debt_ratio_pct": item.debt_ratio_pct,
        "roe_pct": item.roe_pct,
    }


def _latest_annual_fields(item: AnnualMetrics) -> dict[str, Any]:
    return {
        "latest_annual_report_date": item.report_date.isoformat(),
        "latest_annual_period_label": report_period_label(item.report_date),
        "latest_annual_revenue": item.revenue_yuan,
        "latest_annual_net_profit": item.net_profit_yuan,
        "latest_annual_operating_cashflow": item.operating_cashflow_yuan,
        "latest_annual_gross_margin_pct": item.gross_margin_pct,
        "latest_annual_net_margin_pct": item.net_margin_pct,
        "latest_annual_debt_ratio_pct": item.debt_ratio_pct,
    }


def _latest_period_fields(item: AnnualMetrics) -> dict[str, Any]:
    return {
        "latest_period_report_date": item.report_date.isoformat(),
        "latest_period_label": report_period_label(item.report_date),
        "latest_revenue": item.revenue_yuan,
        "latest_net_profit": item.net_profit_yuan,
        "latest_operating_cashflow": item.operating_cashflow_yuan,
        "latest_gross_margin_pct": item.gross_margin_pct,
        "latest_net_margin_pct": item.net_margin_pct,
        "latest_debt_ratio_pct": item.debt_ratio_pct,
        "profitable": item.net_profit_yuan is not None and item.net_profit_yuan > 0,
    }


def extract_financial_quant_metrics(
    financials: StockFinancials,
    *,
    today: date | None = None,
    annual_years: int = 3,
    recent_interim_count: int = 4,
) -> dict[str, Any]:
    """Build prompt-friendly financial metrics including interim/quarterly reports."""
    periods = _sorted_periods(financials, today=today)
    if not periods:
        return {}

    as_of = today or date.today()
    latest_period = periods[-1]
    annual_window = adaptive_annual_window(periods, annual_years)
    latest_annual_window = adaptive_annual_window(periods, 1)
    latest_annual = latest_annual_window[-1] if latest_annual_window else None

    interim_periods = [item for item in periods if not is_annual_report(item.report_date)]
    current_year_interims = [
        item for item in interim_periods if item.report_date.year == as_of.year
    ]

    metrics: dict[str, Any] = {
        "financial_data_as_of": latest_period.report_date.isoformat(),
        "financial_reports_count": len(periods),
        **_latest_period_fields(latest_period),
        "roe_values": [item.roe_pct for item in annual_window],
        "annual_report_dates_3y": [item.report_date.isoformat() for item in annual_window],
        "annual_revenue_values_3y": [item.revenue_yuan for item in annual_window],
        "annual_net_profit_values_3y": [item.net_profit_yuan for item in annual_window],
        "annual_operating_cashflow_values_3y": [
            item.operating_cashflow_yuan for item in annual_window
        ],
        "current_year_interim_reports": [_period_snapshot(item) for item in current_year_interims],
        "recent_interim_reports": [
            _period_snapshot(item) for item in interim_periods[-recent_interim_count:]
        ],
    }

    if latest_annual is not None:
        metrics.update(_latest_annual_fields(latest_annual))

    if latest_annual is not None and latest_period.report_date != latest_annual.report_date:
        metrics["has_newer_interim_than_annual"] = True
    else:
        metrics["has_newer_interim_than_annual"] = False

    metrics.update(extract_business_model_metrics(latest_period, annual_window))
    metrics.update(
        extract_growth_metrics(
            periods,
            latest_period=latest_period,
            latest_annual=latest_annual,
        )
    )

    return metrics


def eps_annual_cagr_pct(annual_window: list[AnnualMetrics]) -> tuple[float | None, bool]:
    """Return (CAGR%, available). Unavailable when EPS missing or any year <= 0."""
    if len(annual_window) < 2:
        return None, False
    values = [item.eps_basic for item in annual_window]
    if any(value is None for value in values):
        return None, False
    if any(value is not None and value <= 0 for value in values):
        return None, False
    years_span = annual_window[-1].report_date.year - annual_window[0].report_date.year
    cagr = revenue_cagr_pct(values, years_span=years_span)
    return cagr, cagr is not None


def rd_to_revenue_pct(
    rd_expense_yuan: float | None,
    revenue_yuan: float | None,
) -> float | None:
    if rd_expense_yuan is None or revenue_yuan is None or revenue_yuan <= 0:
        return None
    if rd_expense_yuan < 0:
        return None
    return round(rd_expense_yuan / revenue_yuan * 100, 2)


def extract_growth_metrics(
    periods: list[AnnualMetrics],
    *,
    latest_period: AnnualMetrics,
    latest_annual: AnnualMetrics | None,
) -> dict[str, Any]:
    annual_3y = adaptive_annual_window(periods, 3)
    annual_5y = adaptive_annual_window(periods, 5)
    eps_cagr_3y, eps_cagr_3y_available = eps_annual_cagr_pct(annual_3y)
    eps_cagr_5y, eps_cagr_5y_available = eps_annual_cagr_pct(annual_5y)

    rd_values_3y = [item.rd_expense_yuan for item in annual_3y]
    rd_to_revenue_values_3y = [
        rd_to_revenue_pct(item.rd_expense_yuan, item.revenue_yuan) for item in annual_3y
    ]

    metrics: dict[str, Any] = {
        "eps_basic_latest_period": latest_period.eps_basic,
        "eps_basic_latest_annual": latest_annual.eps_basic if latest_annual is not None else None,
        "eps_values_3y": [item.eps_basic for item in annual_3y],
        "eps_values_5y": [item.eps_basic for item in annual_5y],
        "eps_cagr_3y": eps_cagr_3y,
        "eps_cagr_5y": eps_cagr_5y,
        "eps_cagr_3y_available": eps_cagr_3y_available,
        "eps_cagr_5y_available": eps_cagr_5y_available,
        "rd_expense_yuan": latest_period.rd_expense_yuan,
        "rd_expense_latest_annual": (
            latest_annual.rd_expense_yuan if latest_annual is not None else None
        ),
        "rd_to_revenue_pct": rd_to_revenue_pct(
            latest_period.rd_expense_yuan,
            latest_period.revenue_yuan,
        ),
        "rd_expense_values_3y": rd_values_3y,
        "rd_to_revenue_pct_values_3y": rd_to_revenue_values_3y,
    }

    if eps_cagr_3y_available and eps_cagr_3y is not None:
        metrics["eps_growth_meets_20pct_3y"] = eps_cagr_3y >= 20.0
        metrics["eps_growth_meets_30pct_3y"] = eps_cagr_3y >= 30.0
    else:
        metrics["eps_growth_meets_20pct_3y"] = None
        metrics["eps_growth_meets_30pct_3y"] = None
        if annual_3y and any(
            item.eps_basic is not None and item.eps_basic <= 0 for item in annual_3y
        ):
            metrics["eps_cagr_3y_note"] = "近3年EPS含非正值，复合增速不适用（常见于困境反转）"
        elif annual_3y:
            metrics["eps_cagr_3y_note"] = "近3年EPS数据不足，无法计算复合增速"

    if not eps_cagr_5y_available and eps_cagr_5y is None and len(annual_5y) >= 2:
        if any(item.eps_basic is not None and item.eps_basic <= 0 for item in annual_5y):
            metrics["eps_cagr_5y_note"] = "近5年EPS含非正值，复合增速不适用"

    if latest_period.rd_expense_yuan is None and (
        latest_annual is None or latest_annual.rd_expense_yuan is None
    ):
        metrics["rd_data_note"] = "未获取到研发费用（部分行业/港股财报可能不披露）"

    return metrics


def revenue_cagr_pct(values: list[float | None], years_span: int | None = None) -> float | None:
    clean = [value for value in values if value is not None and value > 0]
    if len(clean) < 2:
        return None
    first, last = clean[0], clean[-1]
    if first <= 0:
        return None
    span = years_span if years_span is not None and years_span > 0 else len(clean) - 1
    if span <= 0:
        return None
    return round((math.pow(last / first, 1 / span) - 1) * 100, 2)


def classify_cashflow_quality(
    net_profit_yuan: float | None,
    operating_cashflow_yuan: float | None,
    *,
    min_ratio: float = OCF_COVERS_PROFIT_MIN_RATIO,
) -> CashflowQuality:
    if net_profit_yuan is None and operating_cashflow_yuan is None:
        return "missing_data"
    if net_profit_yuan is not None and net_profit_yuan > 0:
        if operating_cashflow_yuan is None:
            return "profit_no_ocf"
        if operating_cashflow_yuan < 0:
            return "both_weak"
        ratio = operating_cashflow_yuan / net_profit_yuan
        if ratio >= min_ratio:
            return "ocf_covers_profit"
        return "ocf_below_profit"
    if operating_cashflow_yuan is not None and operating_cashflow_yuan > 0:
        return "loss_positive_ocf"
    return "both_weak"


def ocf_to_profit_ratio(
    net_profit_yuan: float | None,
    operating_cashflow_yuan: float | None,
) -> float | None:
    if net_profit_yuan is None or net_profit_yuan <= 0:
        return None
    if operating_cashflow_yuan is None:
        return None
    return round(operating_cashflow_yuan / net_profit_yuan, 3)


def _cashflow_quality_note(quality: CashflowQuality) -> str | None:
    notes = {
        "missing_data": "缺少净利润与经营现金流，无法判断利润含金量",
        "both_weak": "利润与经营现金流均偏弱或为负",
        "profit_no_ocf": "有利润但缺少经营现金流数据，需警惕纸面利润",
        "ocf_covers_profit": f"经营现金流/净利润>={OCF_COVERS_PROFIT_MIN_RATIO}，利润含金量较好",
        "ocf_below_profit": f"经营现金流/净利润<{OCF_COVERS_PROFIT_MIN_RATIO}，利润可能偏纸面",
        "loss_positive_ocf": "整体亏损但经营现金流为正，可能处于先投后赚阶段",
    }
    return notes.get(quality)


def extract_business_model_metrics(
    latest_period: AnnualMetrics,
    annual_window: list[AnnualMetrics],
) -> dict[str, Any]:
    """Unit-economics and cash-quality metrics for business-model scoring."""
    profit_values = [item.net_profit_yuan for item in annual_window]
    revenue_values = [item.revenue_yuan for item in annual_window]
    ocf_values = [item.operating_cashflow_yuan for item in annual_window]
    gross_margin_values = [item.gross_margin_pct for item in annual_window]

    profitable_years = sum(
        1 for value in profit_values if value is not None and value > 0
    )
    years_span = None
    if len(annual_window) >= 2:
        years_span = annual_window[-1].report_date.year - annual_window[0].report_date.year

    ratio = ocf_to_profit_ratio(
        latest_period.net_profit_yuan,
        latest_period.operating_cashflow_yuan,
    )
    quality = classify_cashflow_quality(
        latest_period.net_profit_yuan,
        latest_period.operating_cashflow_yuan,
    )

    return {
        "gross_margin_pct": latest_period.gross_margin_pct,
        "net_margin_pct": latest_period.net_margin_pct,
        "debt_ratio_pct": latest_period.debt_ratio_pct,
        "gross_margin_values": gross_margin_values,
        "revenue_values": revenue_values,
        "revenue_cagr_3y": revenue_cagr_pct(revenue_values, years_span=years_span),
        "net_profit_values": profit_values,
        "profitable_years_3y": profitable_years,
        "operating_cashflow_values": ocf_values,
        "ocf_to_profit_ratio": ratio,
        "ocf_to_profit_ratio_basis": "latest_period",
        "ocf_to_profit_ratio_note": (
            "最新一期有利润但缺少经营现金流，无法计算比值"
            if quality == "profit_no_ocf"
            else _cashflow_quality_note(quality)
        ),
        "cashflow_quality": quality,
    }


def latest_annual_profit_and_cashflow(
    financials: StockFinancials | None,
) -> tuple[float | None, float | None, float | None]:
    """Return (revenue, net_profit, operating_cashflow) from the latest annual report."""
    if financials is None:
        return None, None, None
    window = adaptive_annual_window(financials.annual, 1)
    if not window:
        return None, None, None
    latest = window[-1]
    return latest.revenue_yuan, latest.net_profit_yuan, latest.operating_cashflow_yuan
