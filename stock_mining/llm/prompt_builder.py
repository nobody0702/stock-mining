from __future__ import annotations

from stock_mining.llm.dimensions import AnalysisConfig, AnalysisDimension
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
        "- 「内容」列必须以「N分，」开头并接说明文字，N 为 1-5 的整数；说明用几句大白话写清楚，不要只写一句。",
        "- 除「最可能出什么问题」外：分数越高表示该维度越正面、越好。",
        "- 「最可能出什么问题」：分数越高表示风险越大、不确定性越高。",
    ]
    if config.require_rubric_alignment:
        lines.extend(
            [
                "- 每个维度的 N 分必须严格对照下方「统一打分标准」中该维度的 1～5 分定义；",
                "  不同维度之间可以分数不同，但同一分数在不同分析里含义必须一致。",
                "  例如：两个公司护城河都打 4 分，表示它们都符合「4 分」那条标准，而不是各自理解不同。",
            ]
        )

    lines.extend(["", "需要分析的维度如下："])
    for dimension in config.dimensions:
        hint = f"（{dimension.hint}）" if dimension.hint else ""
        lines.append(f"- {dimension.label}{hint}")
        if dimension.rubric:
            lines.append("  统一打分标准：")
            for score in sorted(dimension.rubric):
                lines.append(f"  - {score}分：{dimension.rubric[score]}")

    if config.include_quant_summary:
        lines.extend(["", "以下是程序已经算出的量化信息，供你参考："])
        for key, value in sorted(hit.metrics.items()):
            lines.append(f"- {key}: {value}")

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


def build_batch_prompt(hits: list[CandidateHit], config: AnalysisConfig) -> str:
    chunks = ["请分别分析以下股票，每只股票单独输出一个 Markdown 表格。", ""]
    for hit in hits:
        chunks.append(build_stock_prompt(hit, config))
        chunks.append("\n---\n")
    return "\n".join(chunks)
