from __future__ import annotations

import pandas as pd
import pytest

from stock_mining.config import ScoringConfig, load_pipeline_config
from stock_mining.data.akshare_provider import _normalize_sina_spot_df, _strip_market_prefix
from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit, MarketSnapshot


def test_market_snapshot_auto_drawdown():
    snap = MarketSnapshot("600000", "测试", price=50.0, high_52w=100.0)
    assert snap.drawdown_from_high_pct == pytest.approx(50.0)


def test_candidate_hit_roundtrip_dict():
    hit = CandidateHit(
        "600000",
        "测试",
        Market.A,
        "profitable_growth",
        88.5,
        {"score_cheap": 0.9},
    )
    restored = CandidateHit.from_dict(hit.to_dict())
    assert restored.code == hit.code
    assert restored.market == hit.market
    assert restored.metrics["score_cheap"] == 0.9
    assert hit.stock_key == "a:600000"


def test_strip_market_prefix_normalizes_exchange_codes():
    assert _strip_market_prefix("sh600519") == "600519"
    assert _strip_market_prefix("sz000001") == "000001"
    assert _strip_market_prefix("bj920000") == "920000"


def test_normalize_sina_spot_df_maps_core_columns():
    df = pd.DataFrame(
        {
            "代码": ["sh600519", "sz000001"],
            "名称": ["茅台", "平安"],
            "最新价": [1800.0, 10.5],
        }
    )
    out = _normalize_sina_spot_df(df)
    assert list(out["代码"]) == ["600519", "000001"]
    assert out.iloc[0]["最新价"] == pytest.approx(1800.0)
    assert pd.isna(out.iloc[0]["市盈率-动态"])


def test_screen_yaml_scoring_weights_are_cheap_stability():
    config = load_pipeline_config("config/screen.yaml")
    assert config.scoring.weights["cheap"] == pytest.approx(0.5)
    assert config.scoring.weights["stability"] == pytest.approx(0.5)
    assert ScoringConfig().weights["cheap"] == pytest.approx(0.5)
