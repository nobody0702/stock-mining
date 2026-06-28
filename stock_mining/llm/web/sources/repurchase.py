from __future__ import annotations

from stock_mining.llm.web.models import RepurchaseRecord
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._bulk_cache import get_bulk_dataframe
from stock_mining.llm.web.sources._safe import safe_fetch


def fetch_repurchase_history(
    code: str,
    *,
    limit: int = 5,
    reporter: WebFetchReporter | None = None,
) -> list[RepurchaseRecord]:
    rep = reporter or WebFetchReporter()

    def _load() -> list[RepurchaseRecord]:
        import akshare as ak

        df = get_bulk_dataframe("repurchase_em", ak.stock_repurchase_em)
        if df is None or df.empty:
            return []
        code_col = "股票代码"
        sub = df[df[code_col].astype(str).str.zfill(6) == str(code).zfill(6)]
        if sub.empty:
            return []
        sub = sub.sort_values("最新公告日期", ascending=False)
        records: list[RepurchaseRecord] = []
        for _, row in sub.head(limit).iterrows():
            low = row.get("计划回购金额区间-下限")
            high = row.get("计划回购金额区间-上限")
            amount_range = _format_amount_range(low, high)
            repurchased = row.get("已回购金额")
            records.append(
                RepurchaseRecord(
                    announce_date=_format_date(row.get("最新公告日期")),
                    status=str(row.get("实施进度") or "").strip() or "—",
                    amount_range=amount_range,
                    repurchased_amount=_format_yuan(repurchased),
                )
            )
        return records

    return safe_fetch("回购记录(AkShare stock_repurchase_em)", rep, _load, default=[])


def _format_date(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.split(" ")[0] if " " in text else text[:10]


def _format_yuan(value: object) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "—"
    try:
        yuan = float(value)
        if yuan >= 1e8:
            return f"{yuan / 1e8:.2f}亿元"
        if yuan >= 1e4:
            return f"{yuan / 1e4:.0f}万元"
        return f"{yuan:.0f}元"
    except (TypeError, ValueError):
        return str(value)


def _format_amount_range(low: object, high: object) -> str:
    low_text = _format_yuan(low)
    high_text = _format_yuan(high)
    if low_text == "—" and high_text == "—":
        return "—"
    if low_text == high_text:
        return low_text
    return f"{low_text}～{high_text}"
