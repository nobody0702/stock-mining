from __future__ import annotations

from stock_mining.llm.web.models import DividendRecord
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._safe import safe_fetch


def fetch_dividend_history(
    code: str,
    *,
    limit: int = 8,
    reporter: WebFetchReporter | None = None,
) -> list[DividendRecord]:
    rep = reporter or WebFetchReporter()

    def _load() -> list[DividendRecord]:
        import akshare as ak

        df = ak.stock_history_dividend_detail(symbol=code, indicator="分红")
        if df is None or df.empty:
            return []
        records: list[DividendRecord] = []
        for _, row in df.head(limit).iterrows():
            payout = row.get("派息")
            payout_text = f"每10股派{_format_number(payout)}元" if payout not in (None, "") else "—"
            records.append(
                DividendRecord(
                    date=_format_date(row.get("公告日期")),
                    payout=payout_text,
                    status=str(row.get("进度") or "").strip() or "—",
                )
            )
        return records

    return safe_fetch("分红历史(AkShare stock_history_dividend_detail)", rep, _load, default=[])


def _format_date(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if " " in text:
        return text.split(" ")[0]
    return text[:10] if len(text) >= 10 else text


def _format_number(value: object) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
        if number == int(number):
            return str(int(number))
        return f"{number:.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
