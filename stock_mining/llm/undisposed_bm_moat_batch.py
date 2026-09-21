"""Batch business_model + moat scoring for A-shares not yet in dispositions."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from stock_mining.llm.business_model_batch import merge_batch_markdowns, split_batches
from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
from stock_mining.markets.base import Market
from stock_mining.markets.tags import normalize_legacy_stock_key
from stock_mining.models import CandidateHit, StockInfo

BATCH_SIZE = 10
WORKING_SUBDIR = "undisposed_bm_moat"

DIM_MARKER_BM = "@@DIM:business_model@@"
DIM_MARKER_MOAT = "@@DIM:moat@@"

SYSTEM_PROMPT = (
    "你是 A 股基本面分析助手。"
    "本次只评「商业模式」与「护城河」两个维度，不要评管理层、估值、成长等其他维度。"
    "严格按用户要求输出一个 Markdown 表格，不要输出表格以外的多余章节。"
    "表格列必须是：代码 | 名称 | 商业模式打分 | 商业模式描述 | 护城河打分 | 护城河描述"
    "打分列只写 1-5 的整数；描述用小学生也能懂的大白话，三句话以内。"
)

TABLE_HEADER = (
    "| 代码 | 名称 | 商业模式打分 | 商业模式描述 | 护城河打分 | 护城河描述 |"
)


def get_dimension(config: AnalysisConfig, dimension_id: str) -> AnalysisDimension:
    for dimension in config.dimensions:
        if dimension.id == dimension_id:
            return dimension
    raise ValueError(f"analysis config missing dimension: {dimension_id}")


def load_disposed_stock_keys(dispositions_dir: Path) -> set[str]:
    """Union of stock_key from not_interested / too_expensive / watchlist."""
    keys: set[str] = set()
    for kind in ("not_interested", "too_expensive", "watchlist"):
        path = dispositions_dir / f"{kind}.json"
        if not path.is_file():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            continue
        for row in rows:
            raw = str(row.get("stock_key", "")).strip()
            if raw:
                keys.add(normalize_legacy_stock_key(raw))
    return keys


def filter_undisposed_a_shares(
    stocks: Iterable[StockInfo],
    disposed_keys: set[str],
) -> list[StockInfo]:
    remaining: list[StockInfo] = []
    for stock in stocks:
        if stock.market != Market.A:
            continue
        key = f"a:{stock.code}"
        if key in disposed_keys:
            continue
        remaining.append(stock)
    return remaining


def stocks_to_hits(stocks: Iterable[StockInfo]) -> list[CandidateHit]:
    return [
        CandidateHit(
            code=stock.code,
            name=stock.name,
            market=Market.A,
            track="undisposed",
            score=0.0,
            metrics={},
        )
        for stock in stocks
    ]


def _format_dimension_block(marker: str, dimension: AnalysisDimension) -> list[str]:
    lines = [
        marker,
        f"维度：{dimension.label}",
    ]
    if dimension.hint:
        lines.append(f"提示：{dimension.hint}")
    if dimension.essence:
        lines.append(f"本质：{dimension.essence}")
    if dimension.scoring_checks:
        lines.append("打分前先逐条核对：")
        for check in dimension.scoring_checks:
            lines.append(f"- {check}")
    if dimension.rubric:
        lines.append("统一打分标准（必须整段匹配，不可自行发明标准）：")
        for score in sorted(dimension.rubric):
            lines.append(f"- {score}分：{dimension.rubric[score]}")
    return lines


def build_bm_moat_batch_prompt(
    hits: list[CandidateHit],
    business_model: AnalysisDimension,
    moat: AnalysisDimension,
) -> str:
    lines = [
        f"请对以下 {len(hits)} 只股票分别评「商业模式」与「护城河」（各 1-5 分），"
        "输出一张汇总 Markdown 表格。",
        "请用小学生也能懂的话来回答，不要堆砌术语。",
        "",
        "边界：商业模式与护城河分开评，不要互相串维度；不要评管理层、成长、估值、具体风险。",
        "",
        *_format_dimension_block(DIM_MARKER_BM, business_model),
        "",
        *_format_dimension_block(DIM_MARKER_MOAT, moat),
        "",
        "输出格式（必须严格遵循）：",
        TABLE_HEADER,
        "| --- | --- | --- | --- | --- | --- |",
        "",
        "待分析股票（每只单独打分，全部放入同一张表）：",
    ]
    for hit in hits:
        lines.append(f"- {hit.code} {hit.name}")
    return "\n".join(lines)


def parse_bm_moat_batch_table(text: str) -> list[dict[str, str]]:
    rows = _extract_table_rows(text)
    if len(rows) < 2:
        return []
    header = [cell.strip() for cell in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) < 4:
            continue
        mapped = _map_dual_row(header, row)
        if mapped.get("code"):
            data_rows.append(mapped)
    return data_rows


def format_bm_moat_batch_markdown(
    batch_no: int,
    hits: list[CandidateHit],
    parsed_rows: list[dict[str, str]],
    *,
    raw_response: str = "",
) -> str:
    by_code = {row["code"]: row for row in parsed_rows}
    lines = [
        f"# 商业模式+护城河打分 · 第 {batch_no:02d} 批（{len(hits)} 只）",
        "",
        TABLE_HEADER,
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for hit in hits:
        row = by_code.get(hit.code, {})
        name = row.get("name") or hit.name
        lines.append(
            "| {code} | {name} | {bm} | {bm_desc} | {moat} | {moat_desc} |".format(
                code=hit.code,
                name=name,
                bm=row.get("bm_score", "—"),
                bm_desc=row.get("bm_description", "—"),
                moat=row.get("moat_score", "—"),
                moat_desc=row.get("moat_description", "—"),
            )
        )
    if raw_response:
        lines.extend(
            ["", "<details>", "<summary>原始 LLM 输出</summary>", "", raw_response, "", "</details>"]
        )
    return "\n".join(lines)


def save_undisposed_batches(
    hits: list[CandidateHit],
    working_dir: Path,
    *,
    batch_size: int = BATCH_SIZE,
    meta: dict | None = None,
) -> list[Path]:
    working_dir.mkdir(parents=True, exist_ok=True)
    batches_dir = working_dir / "batches"
    prompts_dir = working_dir / "prompts"
    results_dir = working_dir / "results"
    for path in (batches_dir, prompts_dir, results_dir):
        path.mkdir(parents=True, exist_ok=True)

    stock_list = [hit.to_dict() for hit in hits]
    (working_dir / "stock_list.json").write_text(
        json.dumps({"count": len(stock_list), "stocks": stock_list}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    batches = split_batches(hits, batch_size=batch_size)
    paths: list[Path] = []
    for idx, batch in enumerate(batches, start=1):
        path = batches_dir / f"batch_{idx:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "batch": idx,
                    "count": len(batch),
                    "stocks": [hit.to_dict() for hit in batch],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        paths.append(path)

    status = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "universe_size": (meta or {}).get("universe_size"),
        "disposed": (meta or {}).get("disposed"),
        "remaining": len(hits),
        "batch_count": len(paths),
        "batch_size": batch_size,
        "completed_batches": [],
        "phase": "prepared",
    }
    write_status(working_dir, status)
    return paths


def write_status(working_dir: Path, status: dict) -> None:
    working_dir.mkdir(parents=True, exist_ok=True)
    path = working_dir / "status.json"
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_status(working_dir: Path) -> dict:
    path = working_dir / "status.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def mark_batch_completed(working_dir: Path, batch_no: int) -> None:
    status = read_status(working_dir)
    completed = list(status.get("completed_batches") or [])
    if batch_no not in completed:
        completed.append(batch_no)
    status["completed_batches"] = sorted(completed)
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    status["phase"] = "running"
    write_status(working_dir, status)


def load_batch(path: Path) -> tuple[int, list[CandidateHit]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    batch_no = int(payload["batch"])
    hits = [CandidateHit.from_dict(item) for item in payload["stocks"]]
    return batch_no, hits


def merge_bm_moat_results(results_dir: Path, *, title: str) -> str:
    batch_files = sorted(results_dir.glob("batch_*.md"))
    return merge_batch_markdowns(batch_files, title=title)


def _extract_table_rows(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if "|" in line]
    rows: list[list[str]] = []
    for line in lines:
        if re.match(r"^\|\s*-+", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _map_dual_row(header: list[str], row: list[str]) -> dict[str, str]:
    normalized = [_normalize_dual_header(cell) for cell in header]
    values = row + [""] * max(0, len(normalized) - len(row))
    mapping: dict[str, str] = {}
    for key, value in zip(normalized, values):
        if key == "code":
            mapping["code"] = _normalize_code(value)
        elif key == "name":
            mapping["name"] = value.strip()
        elif key == "bm_score":
            mapping["bm_score"] = _extract_score(value)
        elif key == "bm_description":
            mapping["bm_description"] = value.strip()
        elif key == "moat_score":
            mapping["moat_score"] = _extract_score(value)
        elif key == "moat_description":
            mapping["moat_description"] = value.strip()
    # Fallback positional mapping when headers are generic
    if "bm_score" not in mapping and len(row) >= 6:
        mapping.setdefault("code", _normalize_code(row[0]))
        mapping.setdefault("name", row[1].strip())
        mapping.setdefault("bm_score", _extract_score(row[2]))
        mapping.setdefault("bm_description", row[3].strip())
        mapping.setdefault("moat_score", _extract_score(row[4]))
        mapping.setdefault("moat_description", row[5].strip())
    return mapping


def _normalize_dual_header(cell: str) -> str:
    text = cell.strip().lower()
    if "代码" in text or text == "code":
        return "code"
    if "名称" in text or text == "name":
        return "name"
    if "商业模式" in text and ("打分" in text or "分数" in text):
        return "bm_score"
    if "商业模式" in text and ("描述" in text or "说明" in text):
        return "bm_description"
    if "护城河" in text and ("打分" in text or "分数" in text):
        return "moat_score"
    if "护城河" in text and ("描述" in text or "说明" in text):
        return "moat_description"
    return text


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[-6:] if len(digits) >= 6 else digits


def _extract_score(value: str) -> str:
    match = re.search(r"[1-5]", value)
    return match.group(0) if match else value.strip()
