from __future__ import annotations

from datetime import datetime, timedelta

from stock_mining.llm.web.models import NoticeItem
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._safe import safe_fetch


def fetch_stock_notices(
    code: str,
    *,
    days: int = 365,
    limit: int = 20,
    reporter: WebFetchReporter | None = None,
) -> list[NoticeItem]:
    rep = reporter or WebFetchReporter()

    def _load() -> list[NoticeItem]:
        import akshare as ak

        end = datetime.now().strftime("%Y%m%d")
        begin = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        df = ak.stock_individual_notice_report(
            security=code,
            symbol="全部",
            begin_date=begin,
            end_date=end,
        )
        if df is None or df.empty:
            return []
        items: list[NoticeItem] = []
        for _, row in df.head(limit).iterrows():
            items.append(
                NoticeItem(
                    date=str(row.get("公告日期", "")),
                    title=str(row.get("公告标题", "")).strip(),
                    category=str(row.get("公告类型", "")).strip(),
                )
            )
        return items

    return safe_fetch("公告(AkShare stock_individual_notice_report)", rep, _load, default=[])
