from __future__ import annotations

import json

import pytest
import requests

from stock_mining.markets.base import Market
from stock_mining.markets.hk_connect import AkshareHkConnectProvider
from stock_mining.markets.hk_ggt_sina import fetch_hk_ggt_constituents_sina
from stock_mining.models import StockInfo


def test_fetch_hk_ggt_constituents_sina_parses_pages(monkeypatch):
    monkeypatch.setattr(
        "stock_mining.markets.hk_ggt_sina.call_with_retry",
        lambda fn, **kwargs: fn(),
    )

    def fake_get(url, params=None, timeout=20, proxies=None):
        page = int(params["page"])
        payload: list[dict] = []
        if page == 1:
            payload = [
                {"symbol": "00700", "name": "腾讯控股"},
                {"symbol": "00005", "name": "汇丰控股"},
            ]
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode("utf-8")
        return response

    monkeypatch.setattr("stock_mining.markets.hk_ggt_sina.requests.get", fake_get)

    stocks = fetch_hk_ggt_constituents_sina(network_retries=1, request_interval_sec=0)
    assert len(stocks) == 2
    assert stocks[0].market == Market.HK
    assert stocks[0].code == "00700"


def test_hk_connect_falls_back_to_sina_when_eastmoney_fails(monkeypatch):
    provider = AkshareHkConnectProvider(use_cache=False, network_retries=1)

    def boom():
        raise ConnectionError("eastmoney down")

    monkeypatch.setattr(
        "stock_mining.markets.hk_connect.ak.stock_hk_ggt_components_em",
        boom,
    )
    monkeypatch.setattr(
        "stock_mining.markets.hk_connect.fetch_hk_ggt_constituents_sina",
        lambda **kwargs: [StockInfo("00700", "腾讯控股", Market.HK)],
    )

    stocks = provider.list_stocks()
    assert len(stocks) == 1
    assert stocks[0].code == "00700"


def test_hk_list_resolve_stocks_includes_non_ggt_from_sina(monkeypatch):
    from stock_mining.markets.hk_sina_spot import HkSinaSpotQuote

    provider = AkshareHkConnectProvider(use_cache=False, network_retries=1)
    monkeypatch.setattr(
        provider,
        "list_stocks",
        lambda: [StockInfo("00700", "腾讯控股", Market.HK)],
    )
    provider._sina_spot_quotes = {
        "00700": HkSinaSpotQuote(price=1.0, low_52w=1.0, high_52w=2.0, name="腾讯控股"),
        "01045": HkSinaSpotQuote(price=2.0, low_52w=1.5, high_52w=3.0, name="亚太卫星"),
    }

    resolved = {item.code: item.name for item in provider.list_resolve_stocks()}
    assert resolved["00700"] == "腾讯控股"
    assert resolved["01045"] == "亚太卫星"
