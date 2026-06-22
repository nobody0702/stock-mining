from __future__ import annotations

from typing import Any

from stock_mining.filters.base import Filter, FilterResult
from stock_mining.models import ScreeningContext


class FilterGroupAnyFilter(Filter):
    """Pass if any child filter group passes (each group is AND of its filters)."""

    def __init__(
        self,
        name: str = "filter_group_any",
        groups: list[list[dict[str, Any]]] | None = None,
        **_: object,
    ) -> None:
        from stock_mining.filters.registry import build_filters

        self.name = name
        self.groups = [
            build_filters(group_specs) for group_specs in (groups or [])
        ]

    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        if not self.groups:
            return FilterResult(True, "空 filter group")
        for idx, group in enumerate(self.groups):
            if all(filter_.evaluate(ctx).passed for filter_ in group):
                return FilterResult(True, f"命中子组 {idx + 1}")
        return FilterResult(False, "未命中任何子组")

    @property
    def requires_financials(self) -> bool:
        return any(
            filter_.requires_financials
            for group in self.groups
            for filter_ in group
        )

    @property
    def requires_industry_returns(self) -> bool:
        return any(
            filter_.requires_industry_returns
            for group in self.groups
            for filter_ in group
        )

    @property
    def requires_industry_name(self) -> bool:
        return any(
            filter_.requires_industry_name
            for group in self.groups
            for filter_ in group
        )
