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
        "需要分析的维度如下：",
    ]
    for dimension in config.dimensions:
        hint = f"（{dimension.hint}）" if dimension.hint else ""
        lines.append(f"- {dimension.label}{hint}")

    if config.include_quant_summary:
        lines.extend(["", "以下是程序已经算出的量化信息，供你参考："])
        for key, value in sorted(hit.metrics.items()):
            lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "输出示例：",
            "| 维度 | 内容 |",
            "| --- | --- |",
            "| 怎么赚钱（一句话） | ... |",
        ]
    )
    return "\n".join(lines)


def build_batch_prompt(hits: list[CandidateHit], config: AnalysisConfig) -> str:
    chunks = ["请分别分析以下股票，每只股票单独输出一个 Markdown 表格。", ""]
    for hit in hits:
        chunks.append(build_stock_prompt(hit, config))
        chunks.append("\n---\n")
    return "\n".join(chunks)
