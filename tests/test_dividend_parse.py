from stock_mining.data.akshare_provider import _normalize_dividend_yield


def test_normalize_dividend_yield_fraction():
    assert _normalize_dividend_yield(0.022312) == 2.2312


def test_normalize_dividend_yield_percent():
    assert _normalize_dividend_yield(2.5) == 2.5
