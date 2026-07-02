from __future__ import annotations

import pytest

from stock_mining.markets.base import Market, parse_market
from stock_mining.markets.market_scope import (
    MarketScope,
    market_in_selection,
    markets_for_scope,
    parse_market_scope,
    parse_market_selection,
)
from stock_mining.markets.stock_key import build_stock_key, parse_stock_input, parse_stock_key
from stock_mining.markets.tags import normalize_legacy_stock_key
from stock_mining.models import CandidateHit
from stock_mining.strategies import mining_jobs_for, parse_strategy_selection


def test_market_hk_tag_is_h():
    assert Market.HK.value == "h"
    assert parse_market("hk") == Market.HK


def test_build_stock_key_avoids_collision():
    a_key = build_stock_key(Market.A, "000001")
    h_key = build_stock_key(Market.HK, "00001")
    assert a_key == "a:000001"
    assert h_key == "h:00001"
    assert a_key != h_key


def test_parse_stock_input_tagged():
    market, code = parse_stock_input("a:600519")
    assert market == Market.A
    assert code == "600519"
    market, code = parse_stock_input("h:700")
    assert market == Market.HK
    assert code == "00700"


def test_legacy_hk_stock_key_normalized():
    assert normalize_legacy_stock_key("hk:00700") == "h:00700"
    market, code = parse_stock_key("hk:00700")
    assert market == Market.HK
    assert code == "00700"


def test_candidate_hit_exports_tagged_code():
    hit = CandidateHit("600519", "茅台", Market.A, "t", 80.0, {})
    payload = hit.to_dict()
    assert payload["code"] == "a:600519"
    assert payload["stock_key"] == "a:600519"
    restored = CandidateHit.from_dict(payload)
    assert restored.code == "600519"
    assert restored.stock_key == "a:600519"


def test_candidate_hit_from_legacy_market_field():
    hit = CandidateHit.from_dict(
        {
            "code": "00700",
            "name": "腾讯",
            "market": "hk",
            "track": "t",
            "score": 1.0,
            "metrics": {},
        }
    )
    assert hit.market == Market.HK
    assert hit.stock_key == "h:00700"


def test_mining_jobs_all_expands():
    assert mining_jobs_for("all") == [
        "mispriced_growth",
        "normal_value",
        "mispriced_growth_hk",
    ]


def test_market_scope_all_includes_a_and_h():
    assert markets_for_scope(MarketScope.ALL) == [Market.A, Market.HK]
    assert parse_market_scope("hk") == MarketScope.HK


def test_parse_strategy_selection_comma_list():
    assert parse_strategy_selection("mispriced_growth,normal_value") == [
        "mispriced_growth",
        "normal_value",
    ]
    assert parse_strategy_selection("all") == mining_jobs_for("all")


def test_parse_market_selection_comma_list():
    assert parse_market_selection("a,h") == [Market.A, Market.HK]
    assert parse_market_selection("a,hk") == [Market.A, Market.HK]
    assert market_in_selection(parse_market_selection("a"), Market.A)
    assert not market_in_selection(parse_market_selection("a"), Market.HK)
