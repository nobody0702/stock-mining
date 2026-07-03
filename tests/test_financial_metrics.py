from datetime import date

import pytest

from stock_mining.models import AnnualMetrics, StockFinancials
from stock_mining.scoring.financial_metrics import (
    classify_cashflow_quality,
    eps_annual_cagr_pct,
    extract_business_model_metrics,
    extract_financial_quant_metrics,
    extract_growth_metrics,
    is_annual_report,
    latest_annual_profit_and_cashflow,
    ocf_to_profit_ratio,
    report_period_label,
    revenue_cagr_pct,
)


def test_report_period_label():
    assert report_period_label(date(2026, 3, 31)) == "2026一季报"
    assert report_period_label(date(2026, 6, 30)) == "2026半年报"
    assert report_period_label(date(2025, 12, 31)) == "2025年报"
    assert is_annual_report(date(2025, 12, 31)) is True
    assert is_annual_report(date(2026, 3, 31)) is False


def _item(report_date: date, revenue: float, profit: float) -> AnnualMetrics:
    return AnnualMetrics(
        report_date=report_date,
        revenue_yuan=revenue,
        net_profit_yuan=profit,
        gross_margin_pct=40.0,
        operating_cashflow_yuan=profit * 0.8,
    )


def test_extract_financial_quant_metrics_includes_interim_and_annual():
    financials = StockFinancials(
        "600519",
        annual=[
            _item(date(2023, 12, 31), 100.0, 10.0),
            _item(date(2024, 12, 31), 120.0, 12.0),
            _item(date(2025, 12, 31), 130.0, 13.0),
            _item(date(2026, 3, 31), 35.0, 4.0),
            _item(date(2026, 6, 30), 72.0, 8.0),
        ],
    )
    metrics = extract_financial_quant_metrics(financials, today=date(2026, 8, 15))

    assert metrics["financial_data_as_of"] == "2026-06-30"
    assert metrics["latest_period_label"] == "2026半年报"
    assert metrics["latest_revenue"] == pytest.approx(72.0)
    assert metrics["latest_annual_report_date"] == "2025-12-31"
    assert metrics["latest_annual_revenue"] == pytest.approx(130.0)
    assert metrics["has_newer_interim_than_annual"] is True
    assert len(metrics["current_year_interim_reports"]) == 2
    assert metrics["current_year_interim_reports"][0]["period_label"] == "2026一季报"
    assert metrics["annual_revenue_values_3y"] == pytest.approx([100.0, 120.0, 130.0])
    assert metrics["recent_interim_reports"][-1]["report_date"] == "2026-06-30"


def test_latest_annual_profit_and_cashflow_ignores_interim():
    financials = StockFinancials(
        "600519",
        annual=[
            _item(date(2025, 12, 31), 130.0, 13.0),
            _item(date(2026, 6, 30), 72.0, 8.0),
        ],
    )
    revenue, profit, ocf = latest_annual_profit_and_cashflow(financials)
    assert revenue == pytest.approx(130.0)
    assert profit == pytest.approx(13.0)
    assert ocf == pytest.approx(10.4)


def test_revenue_cagr_pct():
    assert revenue_cagr_pct([100.0, 121.0], years_span=2) == pytest.approx(10.0)


def test_cashflow_quality_and_ocf_ratio():
    assert classify_cashflow_quality(10.0, None) == "profit_no_ocf"
    assert classify_cashflow_quality(10.0, 9.0) == "ocf_covers_profit"
    assert classify_cashflow_quality(10.0, 5.0) == "ocf_below_profit"
    assert classify_cashflow_quality(-1.0, -2.0) == "both_weak"
    assert ocf_to_profit_ratio(10.0, 8.0) == pytest.approx(0.8)
    assert ocf_to_profit_ratio(10.0, None) is None


def test_extract_business_model_metrics_from_latest_period():
    annual_window = [
        AnnualMetrics(
            date(2023, 12, 31),
            revenue_yuan=100.0,
            net_profit_yuan=10.0,
            gross_margin_pct=38.0,
            net_margin_pct=10.0,
            operating_cashflow_yuan=8.0,
            debt_ratio_pct=30.0,
        ),
        AnnualMetrics(
            date(2024, 12, 31),
            revenue_yuan=121.0,
            net_profit_yuan=12.0,
            gross_margin_pct=40.0,
            net_margin_pct=11.0,
            operating_cashflow_yuan=10.0,
            debt_ratio_pct=32.0,
        ),
        AnnualMetrics(
            date(2025, 12, 31),
            revenue_yuan=133.0,
            net_profit_yuan=13.0,
            gross_margin_pct=42.0,
            net_margin_pct=12.0,
            operating_cashflow_yuan=11.0,
            debt_ratio_pct=33.0,
        ),
    ]
    latest = AnnualMetrics(
        date(2026, 6, 30),
        revenue_yuan=72.0,
        net_profit_yuan=8.0,
        gross_margin_pct=45.0,
        net_margin_pct=11.1,
        operating_cashflow_yuan=None,
        debt_ratio_pct=34.0,
    )
    metrics = extract_business_model_metrics(latest, annual_window)

    assert metrics["gross_margin_pct"] == pytest.approx(45.0)
    assert metrics["net_margin_pct"] == pytest.approx(11.1)
    assert metrics["debt_ratio_pct"] == pytest.approx(34.0)
    assert metrics["gross_margin_values"] == pytest.approx([38.0, 40.0, 42.0])
    assert metrics["revenue_values"] == pytest.approx([100.0, 121.0, 133.0])
    assert metrics["revenue_cagr_3y"] == pytest.approx(15.33)
    assert metrics["net_profit_values"] == pytest.approx([10.0, 12.0, 13.0])
    assert metrics["profitable_years_3y"] == 3
    assert metrics["operating_cashflow_values"] == pytest.approx([8.0, 10.0, 11.0])
    assert metrics["ocf_to_profit_ratio"] is None
    assert metrics["cashflow_quality"] == "profit_no_ocf"
    assert "缺少经营现金流" in metrics["ocf_to_profit_ratio_note"]


def test_extract_financial_quant_metrics_includes_business_model_fields():
    financials = StockFinancials(
        "600519",
        annual=[
            _item(date(2024, 12, 31), 120.0, 12.0),
            _item(date(2025, 12, 31), 130.0, 13.0),
            AnnualMetrics(
                date(2026, 6, 30),
                revenue_yuan=72.0,
                net_profit_yuan=8.0,
                gross_margin_pct=45.0,
                net_margin_pct=11.0,
                operating_cashflow_yuan=7.0,
                debt_ratio_pct=35.0,
            ),
        ],
    )
    metrics = extract_financial_quant_metrics(financials, today=date(2026, 8, 1))
    assert "gross_margin_pct" in metrics
    assert metrics["cashflow_quality"] == "ocf_covers_profit"
    assert metrics["ocf_to_profit_ratio"] == pytest.approx(0.875)
    assert "eps_values_3y" in metrics
    assert "rd_to_revenue_pct" in metrics


def test_eps_annual_cagr_pct_requires_positive_eps():
    window = [
        AnnualMetrics(date(2022, 12, 31), eps_basic=1.0),
        AnnualMetrics(date(2023, 12, 31), eps_basic=1.21),
        AnnualMetrics(date(2024, 12, 31), eps_basic=1.4641),
    ]
    cagr, available = eps_annual_cagr_pct(window)
    assert available is True
    assert cagr == pytest.approx(21.0)

    distorted = [
        AnnualMetrics(date(2022, 12, 31), eps_basic=1.0),
        AnnualMetrics(date(2023, 12, 31), eps_basic=-0.5),
        AnnualMetrics(date(2024, 12, 31), eps_basic=1.0),
    ]
    cagr2, available2 = eps_annual_cagr_pct(distorted)
    assert cagr2 is None
    assert available2 is False


def test_extract_growth_metrics_eps_and_rd():
    periods = [
        AnnualMetrics(
            date(2022, 12, 31),
            revenue_yuan=100.0,
            eps_basic=1.0,
            rd_expense_yuan=10.0,
        ),
        AnnualMetrics(
            date(2023, 12, 31),
            revenue_yuan=121.0,
            eps_basic=1.21,
            rd_expense_yuan=12.0,
        ),
        AnnualMetrics(
            date(2024, 12, 31),
            revenue_yuan=146.41,
            eps_basic=1.4641,
            rd_expense_yuan=14.0,
        ),
        AnnualMetrics(
            date(2025, 12, 31),
            revenue_yuan=170.0,
            eps_basic=1.6,
            rd_expense_yuan=16.0,
        ),
        AnnualMetrics(
            date(2026, 6, 30),
            revenue_yuan=90.0,
            eps_basic=0.85,
            rd_expense_yuan=9.0,
        ),
    ]
    metrics = extract_growth_metrics(
        periods,
        latest_period=periods[-1],
        latest_annual=periods[3],
    )
    assert metrics["eps_basic_latest_period"] == pytest.approx(0.85)
    assert metrics["eps_basic_latest_annual"] == pytest.approx(1.6)
    assert metrics["eps_cagr_3y_available"] is True
    assert metrics["eps_growth_meets_20pct_3y"] is False
    assert metrics["rd_to_revenue_pct"] == pytest.approx(10.0)
    assert metrics["rd_expense_values_3y"] == pytest.approx([12.0, 14.0, 16.0])
