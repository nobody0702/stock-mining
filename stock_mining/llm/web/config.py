from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WebContextConfig:
    enabled_by_default: bool = False
    notice_days: int = 365
    max_notices: int = 20
    max_dividend_records: int = 8
    max_repurchase_records: int = 5
    search_queries: tuple[str, ...] = (
        "{name} {code} 财报 分析",
        "{name} 管理层 治理 评价",
        "{name} 争议 处罚 立案",
    )
    max_search_results_per_query: int = 3
    enable_notices: bool = True
    enable_notice_classification: bool = True
    enable_dividends: bool = True
    enable_repurchase: bool = True
    enable_pledge: bool = True
    enable_web_search: bool = True
    jiquer_native_search: bool = False
