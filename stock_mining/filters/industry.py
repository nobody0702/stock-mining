from __future__ import annotations

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.models import ScreeningContext
from stock_mining.utils import industry_matches_keywords


class ExcludeIndustryKeywordsFilter(Filter):
    def __init__(
        self,
        name: str = "exclude_industry_keywords",
        keywords: list[str] | None = None,
        **_: object,
    ) -> None:
        self.name = name
        self.keywords = keywords or []

    @property
    def requires_industry_name(self) -> bool:
        return bool(self.keywords)

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        industry = ctx.market.industry if ctx.market else None
        if industry_matches_keywords(industry, self.keywords):
            return FilterResult(False, f"行业命中排除列表: {industry}")
        return FilterResult(True, "行业未命中排除列表")


class NonDecliningIndustryFilter(Filter):
    def __init__(
        self,
        name: str = "non_declining_industry",
        lookback_years: int = 3,
        min_total_return_pct: float = -15.0,
        skip_if_unavailable: bool = False,
        **_: object,
    ) -> None:
        self.name = name
        self.lookback_years = lookback_years
        self.min_total_return_pct = min_total_return_pct
        self.skip_if_unavailable = skip_if_unavailable

    @property
    def requires_industry_returns(self) -> bool:
        return not self.skip_if_unavailable

    @property
    def requires_industry_name(self) -> bool:
        return True

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        industry = ctx.market.industry if ctx.market else None
        if not industry:
            return FilterResult(False, "缺少行业信息")

        total_return = ctx.industry_return_3y_pct
        if total_return is None:
            if self.skip_if_unavailable:
                return FilterResult(True, f"行业走势不可用，跳过: {industry}")
            return FilterResult(False, f"缺少行业 {industry} 的历史收益")

        if total_return < self.min_total_return_pct:
            return FilterResult(
                False,
                f"行业持续偏弱: {industry} {self.lookback_years}年收益 {total_return:.2f}%",
            )
        return FilterResult(
            True,
            f"行业非持续衰退: {industry} {total_return:.2f}%",
        )
