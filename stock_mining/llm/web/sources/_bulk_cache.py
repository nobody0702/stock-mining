from __future__ import annotations

import time
from typing import Callable, TypeVar

import pandas as pd

T = TypeVar("T")

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_DEFAULT_TTL_SEC = 3600.0


def get_bulk_dataframe(
    key: str,
    fetch: Callable[[], pd.DataFrame],
    *,
    ttl_sec: float = _DEFAULT_TTL_SEC,
) -> pd.DataFrame:
    now = time.time()
    cached = _CACHE.get(key)
    if cached is not None and now - cached[0] < ttl_sec:
        return cached[1]
    df = fetch()
    _CACHE[key] = (now, df)
    return df


def clear_bulk_cache() -> None:
    _CACHE.clear()
