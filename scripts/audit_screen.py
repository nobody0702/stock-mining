#!/usr/bin/env python3
"""Re-evaluate stocks against YAML rules and print per-filter pass/fail."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit stocks against daily_screen.yaml rules")
    parser.add_argument("-c", "--config", default="config/daily_screen.yaml")
    parser.add_argument("--codes", nargs="+", default=None)
    parser.add_argument(
        "--from-csv",
        default=None,
        help="Audit all codes from result CSV, e.g. data/results/daily_screen.csv",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.audit.verifier import audit_context
    from stock_mining.models import StockInfo
    from stock_mining.pipeline.screener import DailyScreener

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    screener = DailyScreener.from_yaml(config_path)
    codes = _resolve_codes(args, root)
    if args.limit is not None:
        codes = codes[: args.limit]

    lookback_years = 3
    for spec in screener.config.filters:
        if spec.get("type") == "non_declining_industry":
            lookback_years = int(spec.get("lookback_years", 3))
            break
    industry_returns = screener.provider.fetch_industry_returns(lookback_years)

    failed = 0
    for code in codes:
        stock = next((s for s in screener.provider.list_stocks() if s.code == code.zfill(6)), None)
        name = stock.name if stock else code
        market = screener.provider.fetch_stock_snapshot(code, name)
        financials = screener.provider.fetch_financials(code)
        ctx = screener._build_context(
            StockInfo(code.zfill(6), name),
            market,
            industry_returns,
            financials,
        )
        report = audit_context(ctx, screener.filters)
        print(f"\n=== {report.code} {report.name} {'PASS' if report.passed else 'FAIL'} ===")
        for note in report.data_notes:
            print(f"  [数据] {note}")
        for row in report.rows:
            mark = "OK" if row.passed else "XX"
            print(f"  [{mark}] {row.filter_name}: {row.reason}")
        if not report.passed:
            failed += 1

    print(f"\n审计 {len(codes)} 只，未通过 {failed} 只")
    return 1 if failed else 0


def _resolve_codes(args: argparse.Namespace, root: Path) -> list[str]:
    if args.codes:
        return [c.zfill(6) for c in args.codes]
    if args.from_csv:
        csv_path = Path(args.from_csv)
        if not csv_path.is_absolute():
            csv_path = root / csv_path
        with csv_path.open(encoding="utf-8-sig") as fp:
            return [row["code"].zfill(6) for row in csv.DictReader(fp)]
    raise SystemExit("请指定 --codes 或 --from-csv")


if __name__ == "__main__":
    raise SystemExit(main())
