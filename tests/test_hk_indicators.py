from __future__ import annotations

import pandas as pd
import pytest

from stock_mining.markets.hk_indicators import parse_hk_indicator_metrics


def test_parse_hk_indicator_metrics_from_em_row():
    row = pd.Series(
        {
            "市盈率": 14.55,
            "市净率": 2.99,
            "股息率TTM(%)": 1.26,
            "总市值(港元)": 3_827_301_258_673.0,
        }
    )
    metrics = parse_hk_indicator_metrics(row)
    assert metrics["pe"] == pytest.approx(14.55)
    assert metrics["pb"] == pytest.approx(2.99)
    assert metrics["dividend_yield_pct"] == pytest.approx(1.26)
    assert metrics["market_cap_yuan"] == pytest.approx(3_827_301_258_673.0)
