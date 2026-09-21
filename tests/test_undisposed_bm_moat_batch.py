from __future__ import annotations

from pathlib import Path

from stock_mining.llm.undisposed_bm_moat_batch import (
    BATCH_SIZE,
    DIM_MARKER_BM,
    DIM_MARKER_MOAT,
    build_bm_moat_batch_prompt,
    filter_undisposed_a_shares,
    format_bm_moat_batch_markdown,
    get_dimension,
    load_disposed_stock_keys,
    parse_bm_moat_batch_table,
    save_undisposed_batches,
    stocks_to_hits,
)
from stock_mining.llm.business_model_batch import split_batches
from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
from stock_mining.markets.base import Market
from stock_mining.models import StockInfo


def test_load_disposed_and_filter_undisposed(tmp_path: Path):
    disp = tmp_path / "dispositions"
    disp.mkdir()
    (disp / "not_interested.json").write_text(
        '[{"stock_key": "a:600001", "name": "甲", "market": "a", '
        '"reference_price": null, "set_at": "2026-01-01T00:00:00", "release_at": null}]\n',
        encoding="utf-8",
    )
    (disp / "too_expensive.json").write_text(
        '[{"stock_key": "a:600002", "name": "乙", "market": "a", '
        '"reference_price": 10, "set_at": "2026-01-01T00:00:00", "release_at": null}]\n',
        encoding="utf-8",
    )
    (disp / "watchlist.json").write_text(
        '[{"stock_key": "hk:00700", "name": "腾讯", "market": "h", '
        '"reference_price": null, "set_at": "2026-01-01T00:00:00", "release_at": null}]\n',
        encoding="utf-8",
    )
    keys = load_disposed_stock_keys(disp)
    assert "a:600001" in keys
    assert "a:600002" in keys
    assert "h:00700" in keys  # legacy hk: normalized

    universe = [
        StockInfo("600001", "甲", Market.A),
        StockInfo("600002", "乙", Market.A),
        StockInfo("600003", "丙", Market.A),
    ]
    remaining = filter_undisposed_a_shares(universe, keys)
    assert [s.code for s in remaining] == ["600003"]


def test_split_batches_size_ten():
    hits = stocks_to_hits(
        [StockInfo(f"{i:06d}", f"名{i}", Market.A) for i in range(1, 26)]
    )
    batches = split_batches(hits, batch_size=BATCH_SIZE)
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 5


def test_save_undisposed_batches_writes_status(tmp_path: Path):
    hits = stocks_to_hits(
        [StockInfo(f"{i:06d}", f"名{i}", Market.A) for i in range(1, 12)]
    )
    paths = save_undisposed_batches(
        hits,
        tmp_path,
        batch_size=10,
        meta={"universe_size": 100, "disposed": 89},
    )
    assert len(paths) == 2
    assert (tmp_path / "stock_list.json").is_file()
    assert (tmp_path / "status.json").is_file()
    status = (tmp_path / "status.json").read_text(encoding="utf-8")
    assert '"remaining": 11' in status
    assert '"batch_count": 2' in status


def test_prompt_contains_dim_markers_and_table_header():
    dims = AnalysisConfig(
        dimensions=(
            AnalysisDimension(
                id="business_model",
                label="商业模式（1-5分）",
                hint="h1",
                ttl_days=90,
                essence="赚钱机器",
                scoring_checks=("谁付钱？",),
                rubric={5: "极清晰"},
            ),
            AnalysisDimension(
                id="moat",
                label="护城河（1-5分）",
                hint="h2",
                ttl_days=90,
                essence="离不开",
                scoring_checks=("涨价走不走？",),
                rubric={5: "定价权清晰"},
            ),
        )
    )
    bm = get_dimension(dims, "business_model")
    moat = get_dimension(dims, "moat")
    hits = stocks_to_hits([StockInfo("600519", "贵州茅台", Market.A)])
    prompt = build_bm_moat_batch_prompt(hits, bm, moat)
    assert DIM_MARKER_BM in prompt
    assert DIM_MARKER_MOAT in prompt
    assert "商业模式打分" in prompt
    assert "护城河打分" in prompt
    assert "600519 贵州茅台" in prompt


def test_parse_and_format_dual_table():
    text = """
杂讯
| 代码 | 名称 | 商业模式打分 | 商业模式描述 | 护城河打分 | 护城河描述 |
| --- | --- | --- | --- | --- | --- |
| 600519 | 贵州茅台 | 5 | 卖酒收钱 | 5 | 品牌壁垒 |
| 000858 | 五粮液 | 4 | 卖酒 | 4 | 较强品牌 |
"""
    rows = parse_bm_moat_batch_table(text)
    assert len(rows) == 2
    assert rows[0]["code"] == "600519"
    assert rows[0]["bm_score"] == "5"
    assert rows[0]["moat_score"] == "5"
    assert rows[1]["bm_score"] == "4"

    hits = stocks_to_hits(
        [
            StockInfo("600519", "贵州茅台", Market.A),
            StockInfo("000858", "五粮液", Market.A),
        ]
    )
    md = format_bm_moat_batch_markdown(1, hits, rows)
    assert "600519" in md
    assert "商业模式+护城河打分" in md
