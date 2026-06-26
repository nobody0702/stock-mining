from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
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


def call_with_timeout(
    fn: Callable[[], T],
    *,
    timeout_sec: float = 30.0,
    retries: int = 1,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 10.0,
) -> T:
    """Run fn in a worker thread and fail if it blocks longer than timeout_sec."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(fn)
                return future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            last_error = TimeoutError(f"operation timed out after {timeout_sec:.0f}s")
            last_error.__cause__ = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt >= retries - 1:
            break
        delay = min(max_delay_sec, base_delay_sec * (2**attempt))
        time.sleep(delay)
    assert last_error is not None
    raise last_error
