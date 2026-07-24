#!/usr/bin/env python3
"""Bulk-add A-share stocks to not_interested by hard rules (ST / 北交所 / low GM).

Rules (any match → not_interested):
  1. ST: stock name contains \"ST\" (case-insensitive)
  2. 北交所: code starts with 4 / 8 / 92
  3. Low gross margin: last 3 full annual reports (12-31) each have
     gross_margin_pct < 20; fewer than 3 years or any missing GM → no match

Cross-machine setup::

    cd stock-mining
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

Preview (no write)::

    python3 scripts/bulk_not_interested_rules.py --dry-run --report /tmp/ni_preview.csv

Apply::

    python3 scripts/bulk_not_interested_rules.py --report /tmp/ni_applied.csv

Useful flags: --limit 50 (smoke), --workers 8, --force, --no-cache,
--suppress-days 365, --dispositions-dir data/state/dispositions,
--max-gross-margin-pct 20, --gm-years 3

Needs AkShare network access; full-market financial fetch can take a while.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


REASON_ST = "st"
REASON_BJ = "bj"
REASON_LOW_GM = "low_gross_margin"


@dataclass(frozen=True)
class RuleHit:
    code: str
    name: str
    reason: str


def classify_st_or_bj(code: str, name: str) -> str | None:
    """Return reason tag if ST or BJ; otherwise None."""
    from stock_mining.utils import is_bj_code, is_st_name

    if is_st_name(name):
        return REASON_ST
    if is_bj_code(code):
        return REASON_BJ
    return None


def is_persistently_low_gross_margin(
    annual: list,
    *,
    years: int = 3,
    max_pct: float = 20.0,
) -> bool:
    """True iff exactly ``years`` annual reports exist and every GM is < max_pct.

    Missing years or any None gross_margin_pct → False.
    Exactly max_pct (e.g. 20.0) does NOT match (strict less-than).
    """
    from stock_mining.utils import annual_window

    window = annual_window(annual, years, annual_only=True)
    if len(window) < years:
        return False
    for item in window:
        gm = item.gross_margin_pct
        if gm is None or gm >= max_pct:
            return False
    return True


def _bootstrap(root: Path) -> None:
    sys.path.insert(0, str(root))
    os.chdir(root)
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def _write_report(path: Path, hits: list[RuleHit]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "name", "reason", "stock_key"])
        writer.writeheader()
        for hit in hits:
            writer.writerow(
                {
                    "code": hit.code,
                    "name": hit.name,
                    "reason": hit.reason,
                    "stock_key": f"a:{hit.code}",
                }
            )


def scan_rule_hits(
    provider,
    *,
    gm_years: int,
    max_gross_margin_pct: float,
    workers: int,
    limit: int | None,
    progress: bool = True,
) -> list[RuleHit]:
    from stock_mining.models import StockInfo

    stocks: list[StockInfo] = list(provider.list_stocks())
    if limit is not None:
        stocks = stocks[: max(0, limit)]

    hits: list[RuleHit] = []
    need_gm: list[StockInfo] = []

    for stock in stocks:
        reason = classify_st_or_bj(stock.code, stock.name)
        if reason is not None:
            hits.append(RuleHit(code=stock.code, name=stock.name, reason=reason))
        else:
            need_gm.append(stock)

    if not need_gm:
        return hits

    cached = provider.fetch_financials_cached({s.code for s in need_gm})
    remaining = [s for s in need_gm if s.code not in cached]

    def _check_fin(code: str, name: str, financials) -> RuleHit | None:
        if financials is None:
            return None
        if is_persistently_low_gross_margin(
            financials.annual,
            years=gm_years,
            max_pct=max_gross_margin_pct,
        ):
            return RuleHit(code=code, name=name, reason=REASON_LOW_GM)
        return None

    for stock in need_gm:
        fin = cached.get(stock.code)
        if fin is None:
            continue
        hit = _check_fin(stock.code, stock.name, fin)
        if hit is not None:
            hits.append(hit)

    if not remaining:
        return hits

    workers = max(1, workers)

    def _fetch_one(stock: StockInfo):
        try:
            return stock, provider.fetch_financials(stock.code, fast=True)
        except Exception:
            return stock, None

    iterator = remaining
    if progress:
        iterator = tqdm(remaining, desc="financials", unit="stk")

    if workers == 1:
        for stock in iterator:
            stock, fin = _fetch_one(stock)
            hit = _check_fin(stock.code, stock.name, fin)
            if hit is not None:
                hits.append(hit)
        return hits

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, stock): stock for stock in remaining}
        done_iter = as_completed(futures)
        if progress:
            done_iter = tqdm(done_iter, total=len(futures), desc="financials", unit="stk")
        for future in done_iter:
            stock, fin = future.result()
            hit = _check_fin(stock.code, stock.name, fin)
            if hit is not None:
                hits.append(hit)

    return hits


def apply_hits(
    store,
    hits: list[RuleHit],
    *,
    suppress_days: int,
    force: bool,
    dry_run: bool,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Write hits to not_interested. Returns (written, skipped_existing)."""
    from stock_mining.state.disposition import DispositionKind

    now = now or datetime.now()
    written = 0
    skipped = 0
    for hit in hits:
        stock_key = f"a:{hit.code}"
        existing = store.get_stock_disposition(stock_key)
        if existing is not None and not force:
            skipped += 1
            continue
        if dry_run:
            written += 1
            continue
        store.set_stock_disposition(
            stock_key,
            hit.name,
            "a",
            DispositionKind.NOT_INTERESTED,
            suppress_days=suppress_days,
            now=now,
        )
        written += 1
    return written, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按 ST / 北交所 / 三年毛利率<阈值 批量写入 not_interested",
    )
    parser.add_argument(
        "--dispositions-dir",
        default="data/state/dispositions",
        help="dispositions JSON 目录",
    )
    parser.add_argument(
        "--state-db",
        default="data/state/user_state.sqlite3",
        help="UserStateStore SQLite 路径",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/cache",
        help="AkShare 本地缓存目录",
    )
    parser.add_argument(
        "--suppress-days",
        type=int,
        default=365,
        help="not_interested release_at = now + N 天（默认 365）",
    )
    parser.add_argument(
        "--max-gross-margin-pct",
        type=float,
        default=20.0,
        help="三年年报毛利率均须严格小于该阈值（%%）",
    )
    parser.add_argument(
        "--gm-years",
        type=int,
        default=3,
        help="连续年报年数（默认 3）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="财务拉取并发数",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅处理 list_stocks 前 N 只（试跑）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已有 disposition（含自选/偏贵）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描与统计，不写 JSON",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用 AkShare 本地缓存",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="写出命中明细 CSV（code,name,reason,stock_key）",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    _bootstrap(root)

    from stock_mining.data.akshare_provider import AkshareDataProvider
    from stock_mining.state.store import UserStateStore

    dispositions_dir = Path(args.dispositions_dir)
    if not dispositions_dir.is_absolute():
        dispositions_dir = root / dispositions_dir
    state_db = Path(args.state_db)
    if not state_db.is_absolute():
        state_db = root / state_db
    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = root / cache_dir

    provider = AkshareDataProvider(
        use_cache=not args.no_cache,
        cache_dir=str(cache_dir),
        request_interval_sec=0.15,
    )
    store = UserStateStore(state_db, dispositions_dir=dispositions_dir)

    print(
        f"扫描 A 股规则 → not_interested "
        f"(dry_run={args.dry_run}, force={args.force}, "
        f"gm<{args.max_gross_margin_pct}% × {args.gm_years}y)"
    )
    hits = scan_rule_hits(
        provider,
        gm_years=args.gm_years,
        max_gross_margin_pct=args.max_gross_margin_pct,
        workers=args.workers,
        limit=args.limit,
    )
    hits = sorted(hits, key=lambda h: (h.reason, h.code))

    by_reason: dict[str, int] = {}
    for hit in hits:
        by_reason[hit.reason] = by_reason.get(hit.reason, 0) + 1

    written, skipped = apply_hits(
        store,
        hits,
        suppress_days=args.suppress_days,
        force=args.force,
        dry_run=args.dry_run,
    )

    if args.report:
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = root / report_path
        _write_report(report_path, hits)
        print(f"报告已写: {report_path}")

    print(f"命中合计: {len(hits)}")
    for reason in (REASON_ST, REASON_BJ, REASON_LOW_GM):
        print(f"  {reason}: {by_reason.get(reason, 0)}")
    print(f"跳过已有处置: {skipped}")
    action = "将写入" if args.dry_run else "已写入"
    print(f"{action}: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
