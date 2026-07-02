from __future__ import annotations

from pathlib import Path

import pytest

from stock_mining.markets.base import Market
from stock_mining.markets.market_scope import MarketScope, market_scope_supports, markets_for_scope
from stock_mining.pipeline.multi_screen import _codes_for_market, run_mining
from stock_mining.pipeline.screener import DailyScreener
from stock_mining.strategies import get_strategy, mining_jobs_for


ROOT = Path(__file__).resolve().parents[1]


def test_codes_for_market_filters_tagged_tokens():
    codes = _codes_for_market(
        ["a:600519", "h:00700", "600036"],
        Market.A,
        default_market=Market.A,
    )
    assert codes == ["600519", "600036"]

    hk_codes = _codes_for_market(
        ["a:600519", "h:00700"],
        Market.HK,
        default_market=Market.HK,
    )
    assert hk_codes == ["00700"]


def test_market_scope_filters_hk_strategy_on_a_only():
    hk_strategy = get_strategy("mispriced_growth_hk")
    assert not market_scope_supports(MarketScope.A, Market.HK)
    assert market_scope_supports(MarketScope.ALL, Market.HK)
    assert markets_for_scope(MarketScope.ALL) == [Market.A, Market.HK]


def test_mining_jobs_all_lists_three():
    assert len(mining_jobs_for("all")) == 3


def test_run_mining_uses_unified_for_multiple_a_strategies(monkeypatch, tmp_path):
    unified_calls: list[tuple[Market, int]] = []
    run_calls: list[int] = []

    def fake_unified(market, screeners, *, universe=None):
        unified_calls.append((market, len(screeners)))
        return [[] for _ in screeners]

    def fake_run(self):
        run_calls.append(1)
        return []

    def fake_save(self, hits):
        json_path = tmp_path / f"{self.config.output.candidates_json}"
        csv_path = tmp_path / "out.csv"
        legacy_path = tmp_path / "legacy.csv"
        json_path.write_text('{"candidates": []}', encoding="utf-8")
        csv_path.write_text("", encoding="utf-8")
        legacy_path.write_text("", encoding="utf-8")
        return json_path, csv_path, legacy_path

    monkeypatch.setattr(
        "stock_mining.pipeline.multi_screen.run_unified_screeners_for_market",
        fake_unified,
    )
    monkeypatch.setattr(DailyScreener, "run", fake_run)
    monkeypatch.setattr(DailyScreener, "save", fake_save)

    results = run_mining(
        ROOT,
        strategy_id="mispriced_growth,normal_value",
        selected_markets=[Market.A],
        state_store=None,
        max_stocks=1,
    )

    assert len(unified_calls) == 1
    assert unified_calls[0] == (Market.A, 2)
    assert run_calls == []
    assert len(results) == 2


def test_run_mining_all_uses_unified_for_a_and_single_for_hk(monkeypatch, tmp_path):
    unified_calls: list[tuple[Market, int]] = []
    run_calls: list[int] = []

    def fake_unified(market, screeners, *, universe=None):
        unified_calls.append((market, len(screeners)))
        return [[] for _ in screeners]

    def fake_run(self):
        run_calls.append(1)
        return []

    def fake_save(self, hits):
        json_path = tmp_path / f"{self.config.output.candidates_json}"
        csv_path = tmp_path / "out.csv"
        legacy_path = tmp_path / "legacy.csv"
        json_path.write_text('{"candidates": []}', encoding="utf-8")
        csv_path.write_text("", encoding="utf-8")
        legacy_path.write_text("", encoding="utf-8")
        return json_path, csv_path, legacy_path

    monkeypatch.setattr(
        "stock_mining.pipeline.multi_screen.run_unified_screeners_for_market",
        fake_unified,
    )
    monkeypatch.setattr(DailyScreener, "run", fake_run)
    monkeypatch.setattr(DailyScreener, "save", fake_save)

    run_mining(
        ROOT,
        strategy_id="all",
        selected_markets=[Market.A, Market.HK],
        state_store=None,
        max_stocks=1,
    )

    assert unified_calls == [(Market.A, 2)]
    assert run_calls == [1]
