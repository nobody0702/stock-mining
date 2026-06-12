from stock_mining.filters.registry import build_filter


def test_build_filter_non_st():
    f = build_filter({"name": "x", "type": "non_st"})
    assert f.name == "x"
