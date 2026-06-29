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
        min_positive_years: int | None = None,
        use_per_share: bool = True,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.require_all_years = require_all_years
        self.min_positive_years = min_positive_years
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

        positive_count = sum(checks)
        if self.min_positive_years is not None:
            passed = positive_count >= self.min_positive_years
            if not passed:
                return FilterResult(
                    False,
                    f"过去{len(window)}年仅 {positive_count} 年经营现金流为正，"
                    f"需要至少 {self.min_positive_years} 年",
                )
            return FilterResult(
                True,
                f"过去{len(window)}年有 {positive_count} 年经营现金流为正",
            )

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


class GrossMarginFlexibleFilter(Filter):
    """At least min_years_meeting years with gross margin >= min_pct in the window.

    If fewer than 2 annual reports exist, require the latest year only.
    """

    def __init__(
        self,
        name: str = "gross_margin_flexible",
        years: int = 3,
        min_pct: float = 40.0,
        min_years_meeting: int = 2,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.min_pct = min_pct
        self.min_years_meeting = min_years_meeting

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

        if len(window) < 2:
            latest = window[-1]
            gm = latest.gross_margin_pct
            if gm is not None and gm >= self.min_pct:
                return FilterResult(True, f"仅{len(window)}年数据，最新毛利率 {gm:.1f}% >= {self.min_pct}%")
            return FilterResult(
                False,
                f"仅{len(window)}年数据，最新毛利率未达 {self.min_pct}%",
            )

        meeting = sum(
            1
            for item in window
            if item.gross_margin_pct is not None and item.gross_margin_pct >= self.min_pct
        )
        if meeting >= self.min_years_meeting:
            return FilterResult(
                True,
                f"过去{len(window)}年有 {meeting} 年毛利率 >= {self.min_pct}%",
            )
        return FilterResult(
            False,
            f"过去{len(window)}年仅 {meeting} 年毛利率 >= {self.min_pct}%，"
            f"需要至少 {self.min_years_meeting} 年",
        )


class RevenueNotSevereDeclineFilter(Filter):
    """Reject sustained revenue declines of at least decline_pct per period.

    With 3+ years: fail when two consecutive YoY drops each exceed decline_pct.
    With 2 years: fail when the single YoY drop exceeds decline_pct.
    With 1 year: pass only if latest gross margin meets gross_margin_fallback_pct.
    """

    def __init__(
        self,
        name: str = "revenue_not_severe_decline",
        years: int = 3,
        decline_pct: float = 10.0,
        gross_margin_fallback_pct: float = 40.0,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.decline_pct = decline_pct
        self.gross_margin_fallback_pct = gross_margin_fallback_pct

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

        if len(window) == 1:
            gm = window[0].gross_margin_pct
            if gm is not None and gm >= self.gross_margin_fallback_pct:
                return FilterResult(
                    True,
                    f"仅1年数据，最新毛利率 {gm:.1f}% >= {self.gross_margin_fallback_pct}%",
                )
            return FilterResult(False, "仅1年数据且毛利率不足")

        revenues = [item.revenue_yuan for item in window if item.revenue_yuan is not None]
        if len(revenues) < 2:
            latest = window[-1]
            gm = latest.gross_margin_pct
            if gm is not None and gm >= self.gross_margin_fallback_pct:
                return FilterResult(True, "收入缺失，按最新毛利率放行")
            return FilterResult(False, "缺少可比收入数据")

        required_consecutive = 2 if len(revenues) >= 3 else 1
        threshold = -self.decline_pct / 100.0
        consecutive = 0
        for idx in range(1, len(revenues)):
            prev, curr = revenues[idx - 1], revenues[idx]
            if prev <= 0:
                consecutive = 0
                continue
            change = (curr - prev) / prev
            if change <= threshold:
                consecutive += 1
                if consecutive >= required_consecutive:
                    return FilterResult(
                        False,
                        f"营收连续{consecutive}期下滑 >= {self.decline_pct}%",
                    )
            else:
                consecutive = 0

        return FilterResult(True, f"过去{len(revenues)}年营收未持续大幅下滑")


class DebtRatioMaxFilter(Filter):
    def __init__(
        self,
        name: str = "debt_ratio_max",
        threshold_pct: float = 40.0,
        years: int = 3,
        use_latest_annual: bool = True,
        inclusive: bool = False,
        **_: object,
    ) -> None:
        self.name = name
        self.threshold_pct = threshold_pct
        self.years = years
        self.use_latest_annual = use_latest_annual
        self.inclusive = inclusive

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

        def _exceeds(ratio: float) -> bool:
            if self.inclusive:
                return ratio > self.threshold_pct
            return ratio >= self.threshold_pct

        if any(_exceeds(ratio) for ratio in ratios):
            bad = next(ratio for ratio in ratios if _exceeds(ratio))
            op = ">" if self.inclusive else ">="
            return FilterResult(
                False,
                f"资产负债率 {bad:.2f}% {op} {self.threshold_pct}%",
            )
        latest = ratios[-1]
        bound = "<=" if self.inclusive else "<"
        return FilterResult(
            True,
            f"过去{len(window)}年资产负债率均 {bound} {self.threshold_pct}%"
            f"（最新 {latest:.2f}%）",
        )


class ProfitNotDeterioratingFilter(Filter):
    def __init__(self, name: str = "profit_not_deteriorating", **_: object) -> None:
        self.name = name

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, 3)
        if len(window) < 2:
            return FilterResult(False, "年报不足，无法判断业绩趋势")
        latest = window[-1]
        prev = window[-2]
        if latest.net_profit_yuan is None or prev.net_profit_yuan is None:
            return FilterResult(False, "缺少净利润")
        if prev.net_profit_yuan <= 0:
            return FilterResult(True, "前一年非盈利，跳过同比判断")
        yoy = (latest.net_profit_yuan - prev.net_profit_yuan) / abs(prev.net_profit_yuan)
        if yoy < -0.05:
            return FilterResult(False, f"最新净利润同比下滑 {yoy * 100:.1f}%")
        if latest.revenue_yuan is not None and prev.revenue_yuan is not None and prev.revenue_yuan > 0:
            rev_yoy = (latest.revenue_yuan - prev.revenue_yuan) / prev.revenue_yuan
            if rev_yoy < -0.05:
                return FilterResult(False, f"最新收入同比下滑 {rev_yoy * 100:.1f}%")
        return FilterResult(True, "业绩未明显恶化")


class RoeNotDecliningFilter(Filter):
    def __init__(self, name: str = "roe_not_declining", years: int = 3, **_: object) -> None:
        self.name = name
        self.years = years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, self.years)
        if len(window) < 2:
            return FilterResult(False, "ROE 数据不足")
        values = [item.roe_pct for item in window if item.roe_pct is not None]
        if len(values) < 2:
            return FilterResult(False, "缺少 ROE")
        if values[-1] + 0.5 < values[0]:
            return FilterResult(False, f"ROE 走弱: {values[0]:.1f}% -> {values[-1]:.1f}%")
        return FilterResult(True, f"ROE 未持续下滑: {values}")


class OcfToProfitMinFilter(Filter):
    def __init__(
        self,
        name: str = "ocf_to_profit_min",
        min_ratio: float = 0.8,
        **_: object,
    ) -> None:
        self.name = name
        self.min_ratio = min_ratio

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, 1)
        if not window:
            return FilterResult(False, "缺少年报")
        latest = window[-1]
        profit = latest.net_profit_yuan
        ocf = latest.operating_cashflow_yuan
        if profit is None or profit <= 0:
            return FilterResult(True, "最新非盈利，跳过现金流含金量")
        if ocf is None:
            per_share = latest.operating_cashflow_per_share
            if per_share is None:
                return FilterResult(False, "缺少经营现金流")
            return FilterResult(True, "仅有每股经营现金流，跳过比值")
        ratio = ocf / profit
        if ratio < self.min_ratio:
            return FilterResult(False, f"经营现金流/净利润={ratio:.2f} < {self.min_ratio}")
        return FilterResult(True, f"经营现金流/净利润={ratio:.2f}")


class ProfitWindowRelaxedFilter(Filter):
    def __init__(
        self,
        name: str = "profit_window_relaxed",
        years: int = 3,
        min_profitable_years: int = 1,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.min_profitable_years = min_profitable_years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少年报")
        profitable = sum(
            1 for item in window if item.net_profit_yuan is not None and item.net_profit_yuan > 0
        )
        if profitable < self.min_profitable_years:
            return FilterResult(
                False,
                f"过去{len(window)}年仅 {profitable} 年盈利，需要至少 {self.min_profitable_years} 年",
            )
        return FilterResult(True, f"过去{len(window)}年有 {profitable} 年盈利")


class RevenueGrowthWindowFilter(Filter):
    def __init__(self, name: str = "revenue_growth_window", years: int = 3, **_: object) -> None:
        self.name = name
        self.years = years

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, self.years)
        revenues = [item.revenue_yuan for item in window if item.revenue_yuan is not None]
        if len(revenues) < 2:
            return FilterResult(True, "收入数据不足，跳过")
        consecutive_decline = 0
        for idx in range(1, len(revenues)):
            if revenues[idx] < revenues[idx - 1]:
                consecutive_decline += 1
                if consecutive_decline >= 2:
                    return FilterResult(False, "收入连续2年下滑")
            else:
                consecutive_decline = 0
        return FilterResult(True, "收入未连续2年下滑")


class GrossMarginMinFilter(Filter):
    def __init__(
        self,
        name: str = "gross_margin_min",
        years: int = 3,
        min_pct: float = 35.0,
        **_: object,
    ) -> None:
        self.name = name
        self.years = years
        self.min_pct = min_pct

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        financials = ctx.financials
        if financials is None:
            return FilterResult(False, "缺少财务数据")
        window = adaptive_annual_window(financials.annual, self.years)
        if not window:
            return FilterResult(False, "缺少年报")
        for metrics in window:
            if metrics.gross_margin_pct is None or metrics.gross_margin_pct < self.min_pct:
                return FilterResult(
                    False,
                    f"毛利率未全部 >= {self.min_pct}%",
                )
        return FilterResult(True, f"过去{len(window)}年毛利率 >= {self.min_pct}%")
