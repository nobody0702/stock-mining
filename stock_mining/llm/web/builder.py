from __future__ import annotations

from typing import Callable

from stock_mining.llm.web.classifier import classify_notices
from stock_mining.llm.web.config import WebContextConfig
from stock_mining.llm.web.models import (
    DividendRecord,
    NoticeItem,
    PledgeSummary,
    RepurchaseRecord,
    SearchHit,
)
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources.dividends import fetch_dividend_history
from stock_mining.llm.web.sources.notices import fetch_stock_notices
from stock_mining.llm.web.sources.pledge import fetch_pledge_summary
from stock_mining.llm.web.sources.repurchase import fetch_repurchase_history
from stock_mining.llm.web.sources.search import search_stock_evidence


def build_web_context(
    code: str,
    name: str,
    *,
    config: WebContextConfig,
    progress: Callable[[str], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> str:
    reporter = WebFetchReporter(on_warning=on_warning)
    sections: list[str] = []
    notices: list[NoticeItem] = []

    if config.enable_notices:
        if progress:
            progress("正在拉取近一年公告…")
        notices = fetch_stock_notices(
            code,
            days=config.notice_days,
            limit=config.max_notices,
            reporter=reporter,
        )
        if notices:
            sections.append(_format_notices(notices))

    if config.enable_notice_classification and notices:
        classified = classify_notices(notices)
        if classified:
            sections.append(_format_classified_notices(classified))

    if config.enable_dividends:
        if progress:
            progress("正在拉取分红历史…")
        dividends = fetch_dividend_history(
            code,
            limit=config.max_dividend_records,
            reporter=reporter,
        )
        if dividends:
            sections.append(_format_dividends(dividends))

    if config.enable_repurchase:
        if progress:
            progress("正在拉取回购记录…")
        repurchases = fetch_repurchase_history(
            code,
            limit=config.max_repurchase_records,
            reporter=reporter,
        )
        if repurchases:
            sections.append(_format_repurchases(repurchases))

    if config.enable_pledge:
        if progress:
            progress("正在查询股权质押…")
        pledge = fetch_pledge_summary(code, reporter=reporter)
        if pledge is not None:
            sections.append(_format_pledge(pledge))

    if config.enable_web_search:
        if progress:
            progress("正在联网检索公开报道…")
        hits = search_stock_evidence(code, name, config, reporter=reporter)
        if hits:
            sections.append(_format_search_hits(hits))

    if not sections:
        return ""

    header = (
        "\n\n---\n"
        "以下是自动搜集的公开信息，请结合上文量化数据与维度标准独立判断；"
        "若无充分证据，宁可打 3 分并说明「公开信息不足」。\n"
    )
    return header + "\n".join(sections) + "\n"


def _format_notices(notices: list[NoticeItem]) -> str:
    lines = ["## 近一年公告摘录（东方财富，供管理层/企业文化等维度参考）"]
    for item in notices:
        lines.append(f"- [{item.date}] {item.category}：{item.title}")
    return "\n".join(lines)


def _format_classified_notices(classified) -> str:
    lines = ["## 公告要点分类（规则自动标注，供管理层/文化/风险维度参考）"]
    for item in classified:
        lines.append(f"- [{item.tag}] [{item.date}] {item.title}")
    return "\n".join(lines)


def _format_dividends(records: list[DividendRecord]) -> str:
    lines = ["## 近年分红记录（AkShare，供管理层资本配置参考）"]
    for item in records:
        lines.append(f"- [{item.date}] {item.payout}（{item.status}）")
    return "\n".join(lines)


def _format_repurchases(records: list[RepurchaseRecord]) -> str:
    lines = ["## 回购记录（AkShare，供管理层资本配置参考）"]
    for item in records:
        lines.append(
            f"- [{item.announce_date}] {item.status}；计划{item.amount_range}；"
            f"已回购{item.repurchased_amount}"
        )
    return "\n".join(lines)


def _format_pledge(pledge: PledgeSummary) -> str:
    return (
        "## 股权质押概况（AkShare）\n"
        f"- 质押比例：{pledge.ratio_pct}（{pledge.detail}）"
    )


def _format_search_hits(hits: list[SearchHit]) -> str:
    lines = ["## 网络检索摘要（请甄别来源，仅作辅助证据，勿照搬）"]
    for hit in hits:
        lines.append(f"- （检索「{hit.query}」）{hit.title}：{hit.snippet}")
    return "\n".join(lines)
