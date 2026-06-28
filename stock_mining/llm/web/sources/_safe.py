from __future__ import annotations

from typing import Callable, TypeVar

from stock_mining.llm.web.reporting import WebFetchReporter

T = TypeVar("T")


def safe_fetch(
    source: str,
    reporter: WebFetchReporter,
    fn: Callable[[], T],
    *,
    default: T,
) -> T:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — network APIs fail unpredictably
        reporter.warn(source, exc)
        return default
