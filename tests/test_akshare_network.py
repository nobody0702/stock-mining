from __future__ import annotations

import importlib

import pytest
import requests


def test_ensure_akshare_direct_connect_sets_trust_env_false(monkeypatch):
    import stock_mining.data.akshare_network as network

    monkeypatch.setattr(network, "_PATCHED", False)
    monkeypatch.delenv("STOCK_MINING_TRUST_PROXY", raising=False)

    trust_env_values: list[bool] = []

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def mount(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            trust_env_values.append(self.trust_env)
            response = requests.Response()
            response.status_code = 200
            return response

    monkeypatch.setattr("stock_mining.data.akshare_network.requests.Session", FakeSession)

    network.ensure_akshare_direct_connect()
    ak_request = importlib.import_module("akshare.utils.request")
    ak_request.request_with_retry("https://example.com")

    assert trust_env_values == [False]


def test_format_proxy_error_detects_proxy_failure():
    from stock_mining.data.akshare_network import format_proxy_error

    exc = requests.exceptions.ProxyError("Unable to connect to proxy")
    message = format_proxy_error(exc)
    assert message is not None
    assert "代理" in message
