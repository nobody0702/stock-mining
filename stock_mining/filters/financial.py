from __future__ import annotations

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.models import ScreeningContext
from stock_mining.utils import adaptive_annual_window


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

        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少年报数据")

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
        return FilterResult(
            True,
            f"过去{len(window)}年利润率条件满足",
        )


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

        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少年报数据")

        checks: list[bool] = []
        for metrics in window:
            ocf = metrics.operating_cashflow_per_share
            if ocf is None:
                checks.append(False)
            else:
                checks.append(ocf > 0)

        passed = all(checks) if self.require_all_years else any(checks)
        if not passed:
            return FilterResult(
                False,
                f"过去{len(window)}年经营现金流未全部为正",
            )
        return FilterResult(
            True,
            f"过去{len(window)}年经营现金流均为正",
        )


class RoeWindowFilter(Filter):
    def __init__(
        self,
        name: str = "roe_window",
        years: int = 5,
        min_pct: float = 8.0,
        high_min_pct: float = 10.0,
        require_all_years: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.min_pct = min_pct
        self.high_min_pct = high_min_pct
        self.require_all_years = require_all_years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少年报数据")

        values: list[float] = []
        for metrics in window:
            if metrics.roe_pct is None:
                return FilterResult(False, "缺少净资产收益率")
            values.append(metrics.roe_pct)

        n = len(values)
        high_count = sum(value > self.high_min_pct for value in values)
        min_count = sum(value > self.min_pct for value in values)
        required_min_count = max(0, n - 2)

        if high_count < 1:
            return FilterResult(
                False,
                f"过去{n}年 ROE 无年份 > {self.high_min_pct}%: {values}",
            )
        if min_count < required_min_count:
            return FilterResult(
                False,
                f"过去{n}年 ROE 仅 {min_count} 年 > {self.min_pct}%，"
                f"需要至少 {required_min_count} 年: {values}",
            )
        return FilterResult(
            True,
            f"过去{n}年 ROE 满足: >{self.high_min_pct}% 至少1年, "
            f">{self.min_pct}% 至少{required_min_count}年",
        )


class DebtRatioMaxFilter(Filter):
    def __init__(
        self,
        name: str = "debt_ratio_max",
        threshold_pct: float = 40.0,
        years: int = 3,
        use_latest_annual: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.threshold_pct = threshold_pct
        self.years = years
        self.use_latest_annual = use_latest_annual

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")

        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少资产负债率")

        ratios: list[float] = []
        for metrics in window:
            if metrics.debt_ratio_pct is None:
                return FilterResult(False, "缺少资产负债率")
            ratios.append(metrics.debt_ratio_pct)

        if any(ratio >= self.threshold_pct for ratio in ratios):
            bad = next(ratio for ratio in ratios if ratio >= self.threshold_pct)
            return FilterResult(
                False,
                f"资产负债率 {bad:.2f}% >= {self.threshold_pct}%",
            )
        latest = ratios[-1]
        return FilterResult(
            True,
            f"过去{len(window)}年资产负债率均 < {self.threshold_pct}%"
            f"（最新 {latest:.2f}%）",
        )
