from __future__ import annotations

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.models import ScreeningContext
from stock_mining.utils import annual_window, is_st_name


class NonStFilter(Filter):
    def __init__(self, name: str = "non_st", **_: object) -> None:
        self.name = name

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        if is_st_name(ctx.stock.name):
            return FilterResult(False, "ST 股票")
        return FilterResult(True, "非 ST")


class Near52WeekLowFilter(Filter):
    def __init__(
        self,
        name: str = "near_52w_low",
        max_price_to_low_ratio: float = 1.05,
        **_: object,
    ) -> None:
        self.name = name
        self.max_price_to_low_ratio = max_price_to_low_ratio

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        market = ctx.market
        if market is None or market.price is None or market.low_52w is None:
            return FilterResult(False, "缺少价格或52周最低")
        if market.low_52w <= 0:
            return FilterResult(False, "52周最低无效")

        ratio = market.price / market.low_52w
        if ratio > self.max_price_to_low_ratio:
            return FilterResult(
                False,
                f"未接近52周新低: 现价/52周低={ratio:.3f}",
            )
        return FilterResult(True, f"接近52周新低: 现价/52周低={ratio:.3f}")


class DividendYieldMinFilter(Filter):
    def __init__(
        self,
        name: str = "dividend_yield_min",
        threshold_pct: float = 2.0,
        **_: object,
    ) -> None:
        self.name = name
        self.threshold_pct = threshold_pct

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        market = ctx.market
        if market is None or market.dividend_yield_pct is None:
            return FilterResult(False, "缺少股息率")
        if market.dividend_yield_pct <= self.threshold_pct:
            return FilterResult(
                False,
                f"股息率 {market.dividend_yield_pct:.2f}% <= {self.threshold_pct}%",
            )
        return FilterResult(True, f"股息率 {market.dividend_yield_pct:.2f}%")


class ValuationByProfitFilter(Filter):
    def __init__(
        self,
        name: str = "valuation_by_profit",
        profit_threshold_yuan: float = 100_000_000,
        pe_max: float = 20,
        pb_max: float = 2,
        ps_max: float = 3,
        **_: object,
    ) -> None:
        self.name = name
        self.profit_threshold_yuan = profit_threshold_yuan
        self.pe_max = pe_max
        self.pb_max = pb_max
        self.ps_max = ps_max

    @property
    def requires_financials(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        market = ctx.market
        financials = ctx.financials
        if market is None or financials is None:
            return FilterResult(False, "缺少行情或财务数据")

        window = annual_window(financials.annual, 1)
        if not window:
            return FilterResult(False, "缺少最新年报利润")
        profit = window[-1].net_profit_yuan
        if profit is None:
            return FilterResult(False, "缺少净利润")

        if profit >= self.profit_threshold_yuan:
            if market.pe is None or market.pe <= 0:
                return FilterResult(False, "大盈利公司缺少有效市盈率")
            if market.pe >= self.pe_max:
                return FilterResult(False, f"PE {market.pe:.2f} >= {self.pe_max}")
            return FilterResult(True, f"大盈利公司 PE {market.pe:.2f} < {self.pe_max}")

        pb_ok = market.pb is not None and market.pb > 0 and market.pb < self.pb_max
        ps_ok = market.ps is not None and market.ps > 0 and market.ps < self.ps_max
        if pb_ok or ps_ok:
            return FilterResult(
                True,
                f"小盈利公司 PB/PS 满足: pb={market.pb}, ps={market.ps}",
            )
        return FilterResult(
            False,
            f"小盈利公司估值不满足: pb={market.pb}, ps={market.ps}",
        )


class DrawdownFromHighMinFilter(Filter):
    def __init__(
        self,
        name: str = "drawdown_from_high_min",
        min_pct: float = 25.0,
        skip_if_missing: bool = False,
        **_: object,
    ) -> None:
        self.name = name
        self.min_pct = min_pct
        self.skip_if_missing = skip_if_missing

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        market = ctx.market
        if market is None:
            return FilterResult(False, "缺少行情")
        drawdown = market.drawdown_from_high_pct
        if drawdown is None:
            if self.skip_if_missing:
                return FilterResult(True, "缺少高点回撤数据，跳过")
            return FilterResult(False, "缺少高点回撤数据")
        if drawdown < self.min_pct:
            return FilterResult(
                False,
                f"距52周高点回撤 {drawdown:.1f}% < {self.min_pct}%",
            )
        return FilterResult(True, f"距52周高点回撤 {drawdown:.1f}%")
