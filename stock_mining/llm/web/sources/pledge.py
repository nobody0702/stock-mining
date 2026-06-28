from __future__ import annotations

from stock_mining.llm.web.models import PledgeSummary
from stock_mining.llm.web.reporting import WebFetchReporter
from stock_mining.llm.web.sources._bulk_cache import get_bulk_dataframe
from stock_mining.llm.web.sources._safe import safe_fetch


def fetch_pledge_summary(
    code: str,
    *,
    reporter: WebFetchReporter | None = None,
) -> PledgeSummary | None:
    rep = reporter or WebFetchReporter()

    def _load() -> PledgeSummary | None:
        try:
            individual = _fetch_individual_pledge(code)
            if individual is not None:
                return individual
        except Exception:
            pass
        return _fetch_market_pledge_ratio(code)

    return safe_fetch("股权质押(AkShare)", rep, _load, default=None)


def _fetch_individual_pledge(code: str) -> PledgeSummary | None:
    import akshare as ak

    df = ak.stock_gpzy_individual_pledge_ratio_detail_em(symbol=code)
    if df is None or df.empty:
        return None
    latest = df.iloc[0]
    ratio = latest.get("质押比例")
    if ratio is None or (isinstance(ratio, float) and ratio != ratio):
        return None
    return PledgeSummary(
        ratio_pct=f"{float(ratio):.2f}%",
        detail="近一期个股质押比例（AkShare）",
    )


def _fetch_market_pledge_ratio(code: str) -> PledgeSummary | None:
    import akshare as ak

    df = get_bulk_dataframe("gpzy_pledge_ratio_em", ak.stock_gpzy_pledge_ratio_em)
    if df is None or df.empty:
        return None
    code_col = "股票代码"
    sub = df[df[code_col].astype(str).str.zfill(6) == str(code).zfill(6)]
    if sub.empty:
        return PledgeSummary(ratio_pct="0%或未披露", detail="未查到质押记录")
    latest = sub.iloc[0]
    ratio = latest.get("质押比例")
    if ratio is None or (isinstance(ratio, float) and ratio != ratio):
        return PledgeSummary(ratio_pct="未披露", detail="质押比例字段缺失")
    return PledgeSummary(
        ratio_pct=f"{float(ratio):.2f}%",
        detail="全市场质押比例表（AkShare）",
    )
