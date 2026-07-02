from __future__ import annotations

from stock_mining.data.akshare_network import ensure_akshare_direct_connect
from stock_mining.data.akshare_provider import AkshareDataProvider, build_data_provider
from stock_mining.data.base import MarketDataProvider
from stock_mining.markets.base import Market
from stock_mining.markets.hk_connect import AkshareHkConnectProvider


def build_market_providers(
    data_source: str,
    markets: list[Market],
    **kwargs: object,
) -> dict[Market, MarketDataProvider]:
    if data_source == "akshare" or Market.HK in markets:
        ensure_akshare_direct_connect()
    providers: dict[Market, MarketDataProvider] = {}
    if Market.A in markets:
        if data_source == "akshare":
            providers[Market.A] = AkshareDataProvider(**kwargs)  # type: ignore[arg-type]
        else:
            providers[Market.A] = build_data_provider(data_source, **kwargs)
    if Market.HK in markets:
        providers[Market.HK] = AkshareHkConnectProvider(**kwargs)  # type: ignore[arg-type]
    return providers
