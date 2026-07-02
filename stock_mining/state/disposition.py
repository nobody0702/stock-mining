from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


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
) -> bool:
    if entry is None or entry.status != "active":
        return False

    kind = entry.disposition
    if kind == DispositionKind.WATCHLIST:
        return True

    if kind == DispositionKind.NOT_INTERESTED:
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
