from __future__ import annotations

from typing import Any

from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
from stock_mining.llm.quant_metric_labels import (
    VALUATION_TIER_FIELD_LABELS,
    format_metric_line,
    group_metric_keys,
)
from stock_mining.models import CandidateHit


def build_stock_prompt(
    hit: CandidateHit,
    config: AnalysisConfig,
) -> str:
    lines = [
        f"请分析股票：{hit.name}（{hit.market.value.upper()}:{hit.code}）",
        "请用一个小学生也能懂的话来回答，不要堆砌术语。",
        "请严格输出 Markdown 表格，第一列必须是「维度」，第二列是「内容」。",
        "",
        "打分规则（每个维度都必须遵守）：",
        "- 「内容」以「N分，」开头（N 为 1～5），接几句大白话说明，勿只写一句。",
        "- 分数越高表示该维度越好。",
    ]
    if config.require_rubric_alignment:
        lines.append(
            "- N 分须对照下方「统一打分标准」；不同公司打同分，须符合同一条标准（如两家护城河都打 4 分，含义一致）。"
        )

    lines.extend(["", "需要分析的维度如下："])
    for dimension in config.dimensions:
        hint = f"（{dimension.hint}）" if dimension.hint else ""
        lines.append(f"- {dimension.label}{hint}")
        if dimension.essence:
            lines.append(f"  本质（本维度只看这个）：{dimension.essence}")
        if dimension.scoring_checks:
            lines.append("  打分前先逐条核对：")
            for check in dimension.scoring_checks:
                lines.append(f"  - {check}")
        if dimension.anti_patterns:
            lines.append("  禁止混用其他维度的判断：")
            for item in dimension.anti_patterns:
                lines.append(f"  - {item}")
        if dimension.rubric:
            lines.append("  统一打分标准（必须整段匹配，不可自行发明标准）：")
            for score in sorted(dimension.rubric):
                lines.append(f"  - {score}分：{dimension.rubric[score]}")
        if dimension.anchors:
            lines.append("  锚定样例（帮助对齐分数，不是必须一模一样）：")
            for score in sorted(dimension.anchors):
                lines.append(f"  - {score}分参考：{dimension.anchors[score]}")

    if config.include_quant_summary:
        lines.extend(_format_quant_summary(hit.metrics))

    example_rows = [f"| {dimension.label} | N分，说明... |" for dimension in config.dimensions]
    lines.extend(
        [
            "",
            "输出示例：",
            "| 维度 | 内容 |",
            "| --- | --- |",
            *example_rows[:3],
            "| ... | ... |",
        ]
    )
    return "\n".join(lines)


def _format_quant_summary(metrics: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "以下是程序已经算出的量化信息，供你参考（每行末尾「—」后为指标含义）：",
        "- 评「商业模式」时优先看「商业模式与单元经济」一节；评「成长性」时优先看「成长性与研发」一节；评「安全边际」时优先看「估值与安全边际」一节。",
    ]

    tier_rows = metrics.get("valuation_tiers")
    if isinstance(tier_rows, list) and tier_rows:
        default_tier = metrics.get("valuation_default_tier", tier_rows[0].get("id"))
        lines.extend(
            [
                "",
                "【估值档位】（多档假设下的 PE 法与简易 DCF 安全边际）",
                "- MOS>0 表示相对该档假设有折扣；MOS<0 表示相对该档假设偏贵。",
                "- 评「安全边际」时，请先根据商业模式、护城河、成长性、行业，",
                "  从下列档位中选出最契合的一档（可说明为何不是其他档），",
                f"  再以该档 MOS 与 intrinsic_price_* 为主依据打分；默认参考档为 {default_tier}。",
                "",
            ]
        )
        for row in tier_rows:
            lines.extend(_format_valuation_tier_row(row))

    general_metrics = {key: value for key, value in metrics.items() if key != "valuation_tiers"}
    if general_metrics:
        for title, keys in group_metric_keys(general_metrics):
            lines.append("")
            lines.append(f"【{title}】")
            for key in keys:
                lines.append(format_metric_line(key, general_metrics[key]))

    return lines


def _format_valuation_tier_row(row: dict[str, Any]) -> list[str]:
    tier_id = row.get("id", "?")
    label = row.get("label", tier_id)
    fair_pe = row.get("fair_pe")
    discount_rate = row.get("discount_rate")
    terminal_growth = row.get("terminal_growth")
    typical_for = row.get("typical_for", "")
    header = (
        f"- [{tier_id}] {label}："
        f"{VALUATION_TIER_FIELD_LABELS['fair_pe']}={fair_pe}，"
        f"{VALUATION_TIER_FIELD_LABELS['discount_rate']}={discount_rate}，"
        f"{VALUATION_TIER_FIELD_LABELS['terminal_growth']}={terminal_growth}"
    )
    if typical_for:
        header += f"  — 常见适用：{typical_for}"
    parts = [header]
    for key in (
        "margin_of_safety_pe_pct",
        "margin_of_safety_dcf_pct",
        "margin_of_safety_pct",
        "intrinsic_price_pe",
        "intrinsic_price_dcf",
        "intrinsic_value_pe_yuan",
        "intrinsic_value_dcf_yuan",
    ):
        if row.get(key) is not None:
            field_label = VALUATION_TIER_FIELD_LABELS.get(key, key)
            parts.append(f"  · {field_label}={row[key]}")
    return parts


def build_batch_prompt(hits: list[CandidateHit], config: AnalysisConfig) -> str:
    chunks = ["请分别分析以下股票，每只股票单独输出一个 Markdown 表格。", ""]
    for hit in hits:
        chunks.append(build_stock_prompt(hit, config))
        chunks.append("\n---\n")
    return "\n".join(chunks)
