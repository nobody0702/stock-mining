from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime

from stock_mining.utils import is_st_name

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class DispositionKind(StrEnum):
    NOT_INTERESTED = "not_interested"
    TOO_EXPENSIVE = "too_expensive"
    WATCHLIST = "watchlist"


DISPOSITION_LABELS: dict[str, str] = {
    DispositionKind.NOT_INTERESTED: "不感兴趣",
    DispositionKind.TOO_EXPENSIVE: "价格偏贵",
    DispositionKind.WATCHLIST: "加入自选",
}

DEFAULT_SUPPRESS_DAYS = 183
SUPPRESS_DAYS_HALF_YEAR = 183
SUPPRESS_DAYS_ONE_YEAR = 365
DEFAULT_TOO_EXPENSIVE_DROP_RATIO = 0.10


@dataclass(frozen=True)
class StockDispositionEntry:
    id: int
    stock_key: str
    name: str
    market: str
    disposition: str
    reference_price: float | None
    set_at: datetime
    release_at: datetime | None
    status: str


def too_expensive_reentry_price(reference_price: float, *, drop_ratio: float) -> float:
    return reference_price * (1.0 - drop_ratio)


def should_suppress_daily_push(
    entry: StockDispositionEntry | None,
    *,
    current_price: float | None,
    now: datetime,
    drop_ratio: float = DEFAULT_TOO_EXPENSIVE_DROP_RATIO,
    current_name: str | None = None,
) -> bool:
    if entry is None or entry.status != "active":
        return False

    kind = entry.disposition
    if kind == DispositionKind.WATCHLIST:
        return True

    if kind == DispositionKind.NOT_INTERESTED:
        # ST 摘帽再入场：存档名曾是 ST，当前名已不是 → 不压制
        if (
            current_name is not None
            and is_st_name(entry.name)
            and not is_st_name(current_name)
        ):
            return False
        if entry.release_at is None:
            return True
        return now < entry.release_at

    if kind == DispositionKind.TOO_EXPENSIVE:
        if entry.release_at is not None and now >= entry.release_at:
            return False
        if entry.reference_price is not None and current_price is not None:
            threshold = too_expensive_reentry_price(entry.reference_price, drop_ratio=drop_ratio)
            if current_price <= threshold:
                return False
        return True

    return False
