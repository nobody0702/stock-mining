from __future__ import annotations

from stock_mining.models import MarketSnapshot


def snapshot_needs_price_enrichment(snapshot: MarketSnapshot | None) -> bool:
    """True when bulk/stub snapshot lacks price data and per-stock fetch is required."""
    if snapshot is None:
        return True
    return snapshot.price is None or snapshot.low_52w is None
