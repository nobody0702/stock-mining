from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from stock_mining.models import ScreeningContext


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str


class Filter(ABC):
    name: str

    @property
    def requires_financials(self) -> bool:
        return False

    @property
    def requires_industry_returns(self) -> bool:
        return False

    @property
    def requires_industry_name(self) -> bool:
        return False

    @abstractmethod
    def evaluate(self, ctx: ScreeningContext) -> FilterResult:
        ...
