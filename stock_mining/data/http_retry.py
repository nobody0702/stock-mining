from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def call_with_retry(
    fn: Callable[[], T],
    *,
    retries: int = 5,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 30.0,
) -> T:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retry on network/data errors
            last_error = exc
            if attempt >= retries - 1:
                break
            delay = min(max_delay_sec, base_delay_sec * (2**attempt))
            time.sleep(delay)
    assert last_error is not None
    raise last_error
