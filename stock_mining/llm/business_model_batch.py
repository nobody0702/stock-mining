from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
from stock_mining.llm.prompt_builder import _format_quant_summary
from stock_mining.models import CandidateHit

BATCH_SIZE = 20
NUM_BATCHES = 11

SYSTEM_PROMPT = (
    "你是 A 股基本面分析助手。"
    "本次只评「商业模式」一个维度，不要评护城河、管理层、估值等其他维度。"
    "严格按用户要求输出一个 Markdown 表格，不要输出表格以外的多余章节。"
    "表格列必须是：代码 | 名称 | 商业模式打分 | 商业模式简单描述 | 扣分理由"
    "「商业模式打分」列只写 1-5 的整数。"
    "「商业模式简单描述」用小学生也能懂的大白话，三句话以内讲清卖什么、谁付钱、为何持续付。"
    "「扣分理由」写本维度为何不能给更高分；若给 5 分可写「无明显扣分项」。"
)

TABLE_HEADER = "| 代码 | 名称 | 商业模式打分 | 商业模式简单描述 | 扣分理由 |"


def get_business_model_dimension(config: AnalysisConfig) -> AnalysisDimension:
    for dimension in config.dimensions:
        if dimension.id == "business_model":
            return dimension
    raise ValueError("analysis config missing business_model dimension")


def build_business_model_batch_prompt(
    hits: list[CandidateHit],
    dimension: AnalysisDimension,
    *,
    include_quant_summary: bool = True,
) -> str:
    lines = [
        f"请对以下 {len(hits)} 只股票分别评「商业模式」维度（1-5 分），输出一张汇总 Markdown 表格。",
        "请用一个小学生也能懂的话来回答，不要堆砌术语。",
        "",
        f"维度：{dimension.label}",
        f"提示：{dimension.hint}" if dimension.hint else "",
        f"本质：{dimension.essence}" if dimension.essence else "",
    ]
    if dimension.scoring_checks:
        lines.append("打分前先逐条核对：")
        for check in dimension.scoring_checks:
            lines.append(f"- {check}")
    if dimension.rubric:
        lines.append("统一打分标准（必须整段匹配，不可自行发明标准）：")
        for score in sorted(dimension.rubric):
            lines.append(f"- {score}分：{dimension.rubric[score]}")
    lines.extend(
        [
            "",
            "边界：护城河、管理层、成长、估值、具体风险各自单独评，不混入本维度。",
            "",
            "输出格式（必须严格遵循）：",
            TABLE_HEADER,
            "| --- | --- | --- | --- | --- |",
            "",
            "待分析股票（每只单独打分，全部放入同一张表）：",
        ]
    )
    for hit in hits:
        lines.append(f"\n### {hit.name}（{hit.market.value.upper()}:{hit.code}）")
        if include_quant_summary and hit.metrics:
            lines.extend(_format_quant_summary(hit.metrics))
    return "\n".join(line for line in lines if line is not None)


def parse_business_model_batch_table(text: str) -> list[dict[str, str]]:
    rows = _extract_table_rows(text)
    if len(rows) < 2:
        return []

    header = [cell.strip() for cell in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        if len(row) < 5:
            continue
        mapped = _map_row(header, row)
        if mapped.get("code"):
            data_rows.append(mapped)
    return data_rows


def format_batch_result_markdown(
    batch_no: int,
    hits: list[CandidateHit],
    parsed_rows: list[dict[str, str]],
    *,
    raw_response: str = "",
) -> str:
    by_code = {row["code"]: row for row in parsed_rows}
    lines = [
        f"# 商业模式打分 · 第 {batch_no:02d} 批（{len(hits)} 只）",
        "",
        TABLE_HEADER,
        "| --- | --- | --- | --- | --- |",
    ]
    for hit in hits:
        row = by_code.get(hit.code, {})
        score = row.get("score", "—")
        desc = row.get("description", "—")
        deduction = row.get("deduction", "—")
        name = row.get("name") or hit.name
        lines.append(f"| {hit.code} | {name} | {score} | {desc} | {deduction} |")
    if raw_response:
        lines.extend(["", "<details>", "<summary>原始 LLM 输出</summary>", "", raw_response, "", "</details>"])
    return "\n".join(lines)


def merge_batch_markdowns(batch_paths: list[Path], *, title: str) -> str:
    sections = [f"# {title}", "", f"共 {len(batch_paths)} 批。", ""]
    for path in batch_paths:
        text = path.read_text(encoding="utf-8")
        body = text.split("\n", 1)[1] if text.startswith("# ") else text
        sections.append(body.strip())
        sections.append("")
        sections.append("---")
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def load_candidates(path: Path) -> list[CandidateHit]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [CandidateHit.from_dict(item) for item in payload["candidates"]]


def split_into_n_batches(hits: list[CandidateHit], n: int) -> list[list[CandidateHit]]:
    total = len(hits)
    base, remainder = divmod(total, n)
    batches: list[list[CandidateHit]] = []
    idx = 0
    for i in range(n):
        count = base + (1 if i < remainder else 0)
        batches.append(hits[idx : idx + count])
        idx += count
    return batches


def split_batches(hits: list[CandidateHit], batch_size: int = BATCH_SIZE) -> list[list[CandidateHit]]:
    return [hits[i : i + batch_size] for i in range(0, len(hits), batch_size)]


def save_batch_manifest(
    hits: list[CandidateHit],
    working_dir: Path,
    *,
    num_batches: int = NUM_BATCHES,
) -> list[Path]:
    working_dir.mkdir(parents=True, exist_ok=True)
    batches_dir = working_dir / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)

    stock_list = [hit.to_dict() for hit in hits]
    (working_dir / "stock_list.json").write_text(
        json.dumps({"count": len(stock_list), "stocks": stock_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    paths: list[Path] = []
    for idx, batch in enumerate(split_into_n_batches(hits, num_batches), start=1):
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
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def load_batch(path: Path) -> tuple[int, list[CandidateHit]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    batch_no = int(payload["batch"])
    hits = [CandidateHit.from_dict(item) for item in payload["stocks"]]
    return batch_no, hits


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


def _map_row(header: list[str], row: list[str]) -> dict[str, str]:
    normalized_header = [_normalize_header(cell) for cell in header]
    values = row + [""] * (len(normalized_header) - len(row))
    mapping: dict[str, str] = {}
    for key, value in zip(normalized_header, values):
        if key == "code":
            mapping["code"] = _normalize_code(value)
        elif key == "name":
            mapping["name"] = value.strip()
        elif key == "score":
            mapping["score"] = _extract_score(value)
        elif key == "description":
            mapping["description"] = value.strip()
        elif key == "deduction":
            mapping["deduction"] = value.strip()
    return mapping


def _normalize_header(cell: str) -> str:
    text = cell.strip().lower()
    if "代码" in text or text == "code":
        return "code"
    if "名称" in text or text == "name":
        return "name"
    if "打分" in text or "分数" in text or text == "score":
        return "score"
    if "描述" in text or "说明" in text:
        return "description"
    if "扣分" in text or "理由" in text:
        return "deduction"
    return text


def _normalize_code(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[-6:] if len(digits) >= 6 else digits


def _extract_score(value: str) -> str:
    match = re.search(r"[1-5]", value)
    return match.group(0) if match else value.strip()
