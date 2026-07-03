"""Tests for data download / request logic (mocked AkShare responses)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stock_mining.data.akshare_provider import (
    AkshareDataProvider,
    _parse_dividend_dataframe,
    _safe_float,
)
from stock_mining.markets.base import Market
from stock_mining.markets.hk_connect import AkshareHkConnectProvider
from stock_mining.markets.hk_sina_spot import HkSinaSpotQuote
from stock_mining.models import AnnualMetrics, MarketSnapshot, StockFinancials


@pytest.fixture
def a_provider(tmp_path: pytest.TempPathFactory) -> AkshareDataProvider:
    return AkshareDataProvider(
        use_cache=True,
        cache_dir=str(tmp_path),
        cache_ttl_hours=12,
        request_interval_sec=0,
        network_retries=1,
        snapshot_workers=2,
    )


@pytest.fixture
def hk_provider(tmp_path: pytest.TempPathFactory) -> AkshareHkConnectProvider:
    return AkshareHkConnectProvider(
        use_cache=True,
        cache_dir=str(tmp_path),
        cache_ttl_hours=12,
        request_interval_sec=0,
        network_retries=1,
    )


def _em_spot_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["600519", "000001", "301001"],
            "名称": ["贵州茅台", "平安银行", "新股样本"],
            "最新价": [1800.0, 10.5, 25.0],
            "市盈率-动态": [28.5, 5.2, 40.0],
            "市净率": [8.1, 0.65, 3.3],
        }
    )


def _dividend_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["600519", "000001", "301001"],
            "现金分红-股息率": [0.015, 2.5, None],
        }
    )


def _hist_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"收盘": closes})


# --- dividend / spot parsing ---


def test_parse_dividend_dataframe_maps_codes_and_normalizes_yield():
    mapping = _parse_dividend_dataframe(_dividend_df())
    assert mapping["600519"] == pytest.approx(1.5)
    assert mapping["000001"] == pytest.approx(2.5)
    assert "301001" not in mapping


def test_parse_dividend_dataframe_rejects_wrong_schema():
    df = pd.DataFrame({"代码": ["600519"], "股息率": [2.0]})
    assert _parse_dividend_dataframe(df) == {}


def test_parse_dividend_does_not_cross_contaminate_codes():
    df = pd.DataFrame(
        {
            "代码": ["600519", "000001"],
            "现金分红-股息率": [0.02, 0.03],
        }
    )
    mapping = _parse_dividend_dataframe(df)
    assert mapping["600519"] == pytest.approx(2.0)
    assert mapping["000001"] == pytest.approx(3.0)
    assert len(mapping) == 2


def test_safe_float_handles_damaged_values():
    assert _safe_float(None) is None
    assert _safe_float("--") is None
    assert _safe_float("") is None
    assert _safe_float("12.34") == pytest.approx(12.34)
    assert _safe_float(float("nan")) is None


def test_list_stocks_normalizes_code_and_assigns_market(monkeypatch, a_provider):
    df = pd.DataFrame({"code": ["1", "600519"], "name": [" 平安银行 ", "贵州茅台"]})

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_info_a_code_name",
        lambda: df,
    )
    stocks = a_provider.list_stocks()
    assert [(s.code, s.name, s.market) for s in stocks] == [
        ("000001", "平安银行", Market.A),
        ("600519", "贵州茅台", Market.A),
    ]


def test_fetch_dividend_map_tries_later_report_date_when_first_empty(monkeypatch, a_provider):
    calls: list[str] = []

    def fake_fhps(*, date: str) -> pd.DataFrame:
        calls.append(date)
        if date == "20251231":
            return pd.DataFrame(columns=["代码", "现金分红-股息率"])
        return _dividend_df()

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_fhps_em",
        fake_fhps,
    )
    mapping = a_provider.fetch_dividend_map()
    assert "600519" in mapping
    assert calls[0] == "20251231"
    assert len(calls) >= 2


def test_fetch_dividend_map_uses_stale_cache_when_all_requests_fail(monkeypatch, a_provider):
    a_provider.cache.set("market", "dividend_map", {"600519": 1.8})

    def boom(_date: str) -> pd.DataFrame:
        raise ConnectionError("network down")

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_fhps_em",
        boom,
    )
    mapping = a_provider.fetch_dividend_map()
    assert mapping["600519"] == pytest.approx(1.8)


# --- bulk spot + snapshot assembly ---


def test_fetch_market_snapshots_maps_em_columns_to_correct_fields(monkeypatch, a_provider):
    monkeypatch.setattr(a_provider, "fetch_dividend_map", lambda: {"600519": 1.5, "000001": 2.5})
    monkeypatch.setattr(a_provider, "_fetch_bulk_spot", lambda: _em_spot_df())
    monkeypatch.setattr(
        a_provider,
        "_enrich_52w_parallel",
        lambda snapshots: None,
    )

    snaps = a_provider.fetch_market_snapshots()
    maotai = snaps["600519"]
    assert maotai.name == "贵州茅台"
    assert maotai.market == Market.A
    assert maotai.price == pytest.approx(1800.0)
    assert maotai.pe == pytest.approx(28.5)
    assert maotai.pe_dynamic == pytest.approx(28.5)
    assert maotai.pe_ttm is None
    assert maotai.pe_static is None
    assert maotai.pb == pytest.approx(8.1)
    assert maotai.dividend_yield_pct == pytest.approx(1.5)


def test_fetch_market_snapshots_filters_requested_codes_only(monkeypatch, a_provider):
    monkeypatch.setattr(a_provider, "fetch_dividend_map", lambda: {})
    monkeypatch.setattr(a_provider, "_fetch_bulk_spot", lambda: _em_spot_df())
    monkeypatch.setattr(a_provider, "_enrich_52w_parallel", lambda snapshots: None)

    snaps = a_provider.fetch_market_snapshots(codes={"600519"})
    assert set(snaps.keys()) == {"600519"}


def test_bulk_spot_falls_back_to_sina_when_eastmoney_fails(monkeypatch, a_provider):
    sina_df = pd.DataFrame(
        {
            "代码": ["sh600519"],
            "名称": ["贵州茅台"],
            "最新价": [1800.0],
        }
    )

    def em_fail() -> pd.DataFrame:
        raise ConnectionError("eastmoney blocked")

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_zh_a_spot_em",
        em_fail,
    )
    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_zh_a_spot",
        lambda: sina_df,
    )

    df = a_provider._fetch_bulk_spot()
    assert list(df["代码"]) == ["600519"]
    assert pd.isna(df.iloc[0]["市盈率-动态"])


def test_merge_cached_snapshot_fills_missing_pe_pb_without_overwriting_price(
    monkeypatch, a_provider
):
    monkeypatch.setattr(a_provider, "fetch_dividend_map", lambda: {})
    monkeypatch.setattr(
        a_provider,
        "_fetch_bulk_spot",
        lambda: pd.DataFrame(
            {
                "代码": ["600519"],
                "名称": ["贵州茅台"],
                "最新价": [1800.0],
                "市盈率-动态": [pd.NA],
                "市净率": [pd.NA],
            }
        ),
    )
    a_provider.cache.set(
        "market",
        "snapshot_600519",
        {
            "code": "600519",
            "name": "贵州茅台",
            "market": "a",
            "price": 1700.0,
            "pe": 30.0,
            "pb": 9.0,
            "ps": 12.0,
            "low_52w": 1500.0,
            "high_52w": 2000.0,
        },
    )
    a_provider._snapshot_payloads = None
    monkeypatch.setattr(a_provider, "_enrich_52w_parallel", lambda snapshots: None)

    snap = a_provider.fetch_market_snapshots()["600519"]
    assert snap.price == pytest.approx(1800.0)
    assert snap.pe == pytest.approx(30.0)
    assert snap.pb == pytest.approx(9.0)
    assert snap.ps == pytest.approx(12.0)
    assert snap.low_52w == pytest.approx(1500.0)


# --- 52-week history ---


def test_fetch_52w_from_hist_uses_recent_closes(monkeypatch, a_provider):
    closes = [float(i) for i in range(1, 301)]

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_zh_a_hist",
        lambda **_: _hist_df(closes),
    )

    stats = a_provider._fetch_52w_from_hist("600519")
    assert stats["low_52w"] == pytest.approx(41.0)
    assert stats["high_52w"] == pytest.approx(300.0)


def test_fetch_52w_from_hist_returns_empty_on_api_failure(monkeypatch, a_provider):
    def boom(**_) -> pd.DataFrame:
        raise ConnectionError("hist failed")

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_zh_a_hist",
        boom,
    )
    stats = a_provider._fetch_52w_from_hist("600519")
    assert stats == {"low_52w": None, "high_52w": None}


def test_enrich_52w_parallel_computes_drawdown_from_high(monkeypatch, a_provider):
    snapshots = {
        "600519": MarketSnapshot(
            "600519",
            "贵州茅台",
            market=Market.A,
            price=80.0,
            pe=20.0,
            pb=5.0,
        )
    }
    a_provider.cache.set(
        "market",
        "week52_600519",
        {"low_52w": 60.0, "high_52w": 100.0},
    )
    a_provider._snapshot_payloads = None

    a_provider._enrich_52w_parallel(snapshots)
    snap = snapshots["600519"]
    assert snap.low_52w == pytest.approx(60.0)
    assert snap.high_52w == pytest.approx(100.0)
    assert snap.drawdown_from_high_pct == pytest.approx(20.0)


def test_enrich_52w_parallel_fetches_missing_codes(monkeypatch, a_provider):
    snapshots = {
        "000001": MarketSnapshot("000001", "平安银行", market=Market.A, price=10.0),
    }

    def fake_52w(code: str) -> dict[str, float | None]:
        assert code == "000001"
        return {"low_52w": 8.0, "high_52w": 15.0}

    monkeypatch.setattr(a_provider, "_fetch_52w_from_hist", fake_52w)
    a_provider._enrich_52w_parallel(snapshots)
    snap = snapshots["000001"]
    assert snap.low_52w == pytest.approx(8.0)
    assert snap.high_52w == pytest.approx(15.0)
    assert snap.drawdown_from_high_pct == pytest.approx(33.333, rel=1e-2)


# --- single-stock valuation ---


def test_fetch_stock_snapshot_maps_value_em_columns(monkeypatch, a_provider):
    value_df = pd.DataFrame(
        {
            "当日收盘价": [1800.0],
            "PE(TTM)": [28.5],
            "PE(静)": [32.0],
            "市净率": [8.1],
            "市销率": [11.2],
        }
    )

    monkeypatch.setattr(a_provider, "fetch_dividend_map", lambda: {"600519": 1.5})
    monkeypatch.setattr(a_provider, "_fetch_industry", lambda code: "白酒")
    monkeypatch.setattr(
        a_provider,
        "_fetch_52w_from_hist",
        lambda code: {"low_52w": 1500.0, "high_52w": 2000.0},
    )
    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_value_em",
        lambda symbol: value_df,
    )

    snap = a_provider.fetch_stock_snapshot("600519", "贵州茅台")
    assert snap.price == pytest.approx(1800.0)
    assert snap.pe == pytest.approx(28.5)
    assert snap.pe_ttm == pytest.approx(28.5)
    assert snap.pe_static == pytest.approx(32.0)
    assert snap.pe_dynamic is None
    assert snap.pb == pytest.approx(8.1)
    assert snap.ps == pytest.approx(11.2)
    assert snap.industry == "白酒"
    assert snap.dividend_yield_pct == pytest.approx(1.5)
    assert snap.low_52w == pytest.approx(1500.0)
    assert snap.drawdown_from_high_pct == pytest.approx(10.0)


def test_fetch_stock_snapshot_does_not_swap_pe_and_pb(monkeypatch, a_provider):
    value_df = pd.DataFrame(
        {
            "当日收盘价": [10.0],
            "PE(TTM)": [99.0],
            "市净率": [1.1],
            "市销率": [2.2],
        }
    )

    monkeypatch.setattr(a_provider, "fetch_dividend_map", lambda: {})
    monkeypatch.setattr(a_provider, "_fetch_industry", lambda code: None)
    monkeypatch.setattr(
        a_provider,
        "_fetch_52w_from_hist",
        lambda code: {"low_52w": 8.0, "high_52w": 12.0},
    )
    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_value_em",
        lambda symbol: value_df,
    )

    snap = a_provider.fetch_stock_snapshot("000001", "测试")
    assert snap.pe == pytest.approx(99.0)
    assert snap.pb == pytest.approx(1.1)
    assert snap.ps == pytest.approx(2.2)


# --- A-share financials ---


def test_parse_financials_maps_ths_columns_and_sorts_by_date(a_provider):
    df = pd.DataFrame(
        [
            {
                "报告期": "2024-12-31",
                "净利润": 100.0,
                "营业总收入": 500.0,
                "销售毛利率": "45.5%",
                "销售净利率": "20%",
                "每股经营现金流": 1.23,
                "经营现金流量净额": 80.0,
                "资产负债率": "35%",
                "净资产收益率": "12.5%",
                "基本每股收益": 10.5,
            },
            {
                "报告期": "2023-12-31",
                "净利润": 90.0,
                "营业收入": 450.0,
                "销售毛利率": "44%",
                "销售净利率": "19%",
                "每股经营现金流": 1.1,
                "经营现金流量净额": 70.0,
                "资产负债率": "36%",
                "净资产收益率": "11%",
            },
            {
                "报告期": "2099-12-31",
                "净利润": 999.0,
                "营业总收入": 9999.0,
            },
        ]
    )
    fin = a_provider._parse_financials("600519", df)
    assert len(fin.annual) == 2
    assert fin.annual[0].report_date == date(2023, 12, 31)
    assert fin.annual[1].report_date == date(2024, 12, 31)
    latest = fin.annual[-1]
    assert latest.net_profit_yuan == pytest.approx(100.0)
    assert latest.revenue_yuan == pytest.approx(500.0)
    assert latest.gross_margin_pct == pytest.approx(45.5)
    assert latest.roe_pct == pytest.approx(12.5)
    assert latest.debt_ratio_pct == pytest.approx(35.0)
    assert latest.eps_basic == pytest.approx(10.5)


def test_parse_financials_does_not_swap_profit_and_revenue(a_provider):
    df = pd.DataFrame(
        [
            {
                "报告期": "2024-12-31",
                "净利润": 111.0,
                "营业总收入": 999.0,
                "净资产收益率": "10%",
            }
        ]
    )
    fin = a_provider._parse_financials("600519", df)
    row = fin.annual[0]
    assert row.net_profit_yuan == pytest.approx(111.0)
    assert row.revenue_yuan == pytest.approx(999.0)


def test_parse_financials_empty_and_damaged_input(a_provider):
    assert a_provider._parse_financials("600519", pd.DataFrame()).annual == []
    df = pd.DataFrame([{"报告期": None, "净利润": 1.0}])
    assert a_provider._parse_financials("600519", df).annual == []


def test_apply_rd_expense_map_merges_by_report_date(a_provider):
    financials = StockFinancials(
        "688001",
        annual=[
            AnnualMetrics(date(2024, 12, 31), revenue_yuan=100.0),
            AnnualMetrics(date(2025, 12, 31), revenue_yuan=120.0),
        ],
    )
    merged = a_provider._apply_rd_expense_map(
        financials,
        {
            date(2024, 12, 31): 10_000_000.0,
            date(2025, 12, 31): 15_000_000.0,
        },
    )
    assert merged.annual[0].rd_expense_yuan == pytest.approx(10_000_000.0)
    assert merged.annual[1].rd_expense_yuan == pytest.approx(15_000_000.0)


def test_fetch_financials_roundtrips_through_cache(monkeypatch, a_provider):
    df = pd.DataFrame(
        [
            {
                "报告期": "2024-12-31",
                "净利润": 50.0,
                "营业总收入": 200.0,
                "净资产收益率": "15%",
            }
        ]
    )
    calls = {"n": 0}

    def fetch_once(symbol: str) -> pd.DataFrame:
        calls["n"] += 1
        return df

    monkeypatch.setattr(
        "stock_mining.data.akshare_provider.ak.stock_financial_abstract_ths",
        fetch_once,
    )
    monkeypatch.setattr(a_provider, "_fetch_rd_expense_map", lambda code, fast=False: {})

    first = a_provider.fetch_financials("600519")
    second = a_provider.fetch_financials("600519")
    assert calls["n"] == 1
    assert first.annual[0].net_profit_yuan == pytest.approx(50.0)
    assert second.annual[0].roe_pct == pytest.approx(15.0)


# --- HK provider ---


def test_hk_list_stocks_normalizes_codes(monkeypatch, hk_provider):
    df = pd.DataFrame({"代码": ["700", "9988"], "名称": ["腾讯", "阿里"]})

    monkeypatch.setattr(
        "stock_mining.markets.hk_connect.ak.stock_hk_ggt_components_em",
        lambda: df,
    )
    stocks = hk_provider.list_stocks()
    assert [(s.code, s.name) for s in stocks] == [
        ("00700", "腾讯"),
        ("09988", "阿里"),
    ]


def test_hk_fetch_valuation_uses_daily_close_not_open(monkeypatch, hk_provider):
    hk_provider._sina_spot_quotes = {}
    df = pd.DataFrame(
        {
            "close": [100.0] * 259 + [120.0],
            "open": [50.0] * 260,
        }
    )

    monkeypatch.setattr(
        "stock_mining.markets.hk_connect.ak.stock_hk_daily",
        lambda symbol, adjust: df,
    )

    val = hk_provider._fetch_valuation("00700")
    assert val["price"] == pytest.approx(120.0)
    assert val["low_52w"] == pytest.approx(100.0)
    assert val["high_52w"] == pytest.approx(120.0)
    assert val["drawdown_from_high_pct"] == pytest.approx(0.0)


def test_hk_fetch_valuation_prefers_sina_spot_quotes(hk_provider):
    hk_provider._sina_spot_quotes = {
        "00700": HkSinaSpotQuote(price=50.0, low_52w=45.0, high_52w=100.0),
    }
    val = hk_provider._fetch_valuation("00700")
    assert val["price"] == pytest.approx(50.0)
    assert val["low_52w"] == pytest.approx(45.0)
    assert val["drawdown_from_high_pct"] == pytest.approx(50.0)


def test_hk_parse_financials_supports_bilingual_columns(hk_provider):
    df = pd.DataFrame(
        [
            {
                "REPORT_DATE": "2024-12-31",
                "HOLDER_PROFIT": 888.0,
                "OPERATE_INCOME": 5000.0,
                "ROE": "18%",
                "DEBT_ASSET_RATIO": "40%",
            },
            {
                "报告期": "2023-12-31",
                "净利润": 700.0,
                "营业收入": 4200.0,
                "净资产收益率": "16%",
                "资产负债率": "41%",
            },
        ]
    )
    fin = hk_provider._parse_financials("00700", df)
    assert len(fin.annual) == 2
    assert fin.market == Market.HK
    assert fin.annual[0].net_profit_yuan == pytest.approx(700.0)
    assert fin.annual[1].net_profit_yuan == pytest.approx(888.0)
    assert fin.annual[1].revenue_yuan == pytest.approx(5000.0)
    assert fin.annual[1].roe_pct == pytest.approx(18.0)


def test_hk_fetch_valuation_returns_none_fields_on_failure(monkeypatch, hk_provider):
    hk_provider._sina_spot_quotes = {}
    monkeypatch.setattr(
        "stock_mining.markets.hk_connect.ak.stock_hk_daily",
        lambda symbol, adjust: (_ for _ in ()).throw(ConnectionError("down")),
    )
    val = hk_provider._fetch_valuation("00700")
    assert val["price"] is None
    assert val["low_52w"] is None
    assert val["drawdown_from_high_pct"] is None
