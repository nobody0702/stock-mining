from stock_mining.filters.registry import build_filter


def test_build_filter_non_st():
    f = build_filter({"name": "x", "type": "non_st"})
    assert f.name == "x"


def test_build_new_filters():
    assert build_filter({"type": "drawdown_from_high_min"}).name == "drawdown_from_high_min"
    assert build_filter({"type": "profit_window_relaxed"}).name == "profit_window_relaxed"
