from __future__ import annotations

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.models import ScreeningContext
from stock_mining.utils import annual_window


class MarginOrWindowFilter(Filter):
    """Each year in window must satisfy gross_margin > X OR net_margin > Y."""

    def __init__(
        self,
        name: str = "margin_or_window",
        years: int = 3,
        gross_margin_min_pct: float = 40.0,
        net_margin_min_pct: float = 20.0,
        require_all_years: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.gross_margin_min_pct = gross_margin_min_pct
        self.net_margin_min_pct = net_margin_min_pct
        self.require_all_years = require_all_years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = annual_window(financials.annual, self.years)
        if len(window) < self.years:
            return FilterResult(False, f"年报不足 {self.years} 年")

        year_results: list[bool] = []
        for metrics in window:
            gross_ok = (
                metrics.gross_margin_pct is not None
                and metrics.gross_margin_pct > self.gross_margin_min_pct
            )
            net_ok = (
                metrics.net_margin_pct is not None
                and metrics.net_margin_pct > self.net_margin_min_pct
            )
            year_results.append(gross_ok or net_ok)

        passed = all(year_results) if self.require_all_years else any(year_results)
        if not passed:
            return FilterResult(
                False,
                f"利润率条件未满足: gross>{self.gross_margin_min_pct}% "
                f"or net>{self.net_margin_min_pct}%",
            )
        return FilterResult(True, "过去3年利润率条件满足")


class OperatingCashflowWindowFilter(Filter):
    def __init__(
        self,
        name: str = "operating_cashflow_window",
        years: int = 3,
        require_all_years: bool = True,
        use_per_share: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.require_all_years = require_all_years
        self.use_per_share = use_per_share

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = annual_window(financials.annual, self.years)
        if len(window) < self.years:
            return FilterResult(False, f"年报不足 {self.years} 年")

        checks: list[bool] = []
        for metrics in window:
            ocf = metrics.operating_cashflow_per_share
            if ocf is None:
                checks.append(False)
            else:
                checks.append(ocf > 0)

        passed = all(checks) if self.require_all_years else any(checks)
        if not passed:
            return FilterResult(False, "过去3年经营现金流未全部为正")
        return FilterResult(True, "过去3年经营现金流均为正")


class RoeWindowFilter(Filter):
    def __init__(
        self,
        name: str = "roe_window",
        years: int = 3,
        min_pct: float = 8.0,
        require_all_years: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.min_pct = min_pct
        self.require_all_years = require_all_years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = annual_window(financials.annual, self.years)
        if len(window) < self.years:
            return FilterResult(False, f"年报不足 {self.years} 年")

        values: list[float] = []
        for metrics in window:
            if metrics.roe_pct is None:
                return FilterResult(False, "缺少净资产收益率")
            values.append(metrics.roe_pct)

        checks = [value > self.min_pct for value in values]
        passed = all(checks) if self.require_all_years else any(checks)
        if not passed:
            return FilterResult(
                False,
                f"过去{self.years}年 ROE 未全部 > {self.min_pct}%: {values}",
            )
        return FilterResult(True, f"过去{self.years}年 ROE 均 > {self.min_pct}%")


class DebtRatioMaxFilter(Filter):
    def __init__(
        self,
        name: str = "debt_ratio_max",
        threshold_pct: float = 40.0,
        use_latest_annual: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.threshold_pct = threshold_pct
        self.use_latest_annual = use_latest_annual

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = annual_window(financials.annual, 1)
        if not window:
            return FilterResult(False, "缺少资产负债率")
        debt_ratio = window[-1].debt_ratio_pct
        if debt_ratio is None:
            return FilterResult(False, "缺少资产负债率")
        if debt_ratio >= self.threshold_pct:
            return FilterResult(
                False,
                f"资产负债率 {debt_ratio:.2f}% >= {self.threshold_pct}%",
            )
        return FilterResult(True, f"资产负债率 {debt_ratio:.2f}%")
