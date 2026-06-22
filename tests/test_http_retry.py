from __future__ import annotations

import pytest

from stock_mining.data.http_retry import call_with_retry


def test_call_with_retry_recovers_after_transient_errors(monkeypatch):
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary")
        return "ok"

    monkeypatch.setattr("stock_mining.data.http_retry.time.sleep", lambda *_: None)
    assert call_with_retry(flaky, retries=5, base_delay_sec=0.01) == "ok"
    assert attempts["count"] == 3


def test_call_with_retry_raises_last_error_when_exhausted(monkeypatch):
    def always_fail() -> None:
        raise ValueError("boom")

    monkeypatch.setattr("stock_mining.data.http_retry.time.sleep", lambda *_: None)
    with pytest.raises(ValueError, match="boom"):
        call_with_retry(always_fail, retries=2, base_delay_sec=0.01)
