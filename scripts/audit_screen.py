#!/usr/bin/env python3
"""Re-evaluate stocks against YAML rules and print per-filter pass/fail."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit stocks against screen.yaml rules")
    parser.add_argument("-c", "--config", default="config/screen.yaml")
    parser.add_argument("--codes", nargs="+", default=None)
    parser.add_argument(
        "--market",
        choices=["a", "hk"],
        default="a",
        help="Market for manual codes",
    )
    parser.add_argument(
        "--from-csv",
        default=None,
        help="Audit all codes from result CSV",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.audit.verifier import audit_context
    from stock_mining.markets.base import Market, normalize_stock_code
    from stock_mining.models import StockInfo
    from stock_mining.pipeline.screener import DailyScreener

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    screener = DailyScreener.from_yaml(config_path, state_store=None)
    market = Market(args.market)
    provider = screener.providers[market]
    codes = _resolve_codes(args, root, market)
    if args.limit is not None:
        codes = codes[: args.limit]

    common_filters = screener.common_filters
    tracks = screener.tracks

    lookback_years = 3
    for spec in screener.config.common_filters:
        if spec.get("type") == "non_declining_industry":
            lookback_years = int(spec.get("lookback_years", 3))
            break
    industry_returns = provider.fetch_industry_returns(lookback_years)

    failed = 0
    for code in codes:
        stock = next((s for s in provider.list_stocks() if s.code == code), None)
        name = stock.name if stock else code
        market_snapshot = provider.fetch_stock_snapshot(code, name)
        financials = provider.fetch_financials(code)
        ctx = screener._build_context(
            StockInfo(code=code, name=name, market=market),
            market_snapshot,
            industry_returns,
            financials,
        )
        print(f"\n=== {market.value}:{code} {name} ===")
        print("  [common]")
        report = audit_context(ctx, common_filters)
        for row in report.rows:
            mark = "OK" if row.passed else "XX"
            print(f"  [{mark}] {row.filter_name}: {row.reason}")
        for track in tracks:
            track_report = audit_context(ctx, track.filters)
            passed = track_report.passed
            print(f"  [track:{track.name}] {'PASS' if passed else 'FAIL'}")
            for row in track_report.rows:
                mark = "OK" if row.passed else "XX"
                print(f"    [{mark}] {row.filter_name}: {row.reason}")
        if not report.passed:
            failed += 1

    print(f"\n审计 {len(codes)} 只，common 未通过 {failed} 只")
    return 1 if failed else 0


def _resolve_codes(args: argparse.Namespace, root: Path, market: Market) -> list[str]:
    if args.codes:
        return [normalize_stock_code(code, market) for code in args.codes]
    if args.from_csv:
        csv_path = Path(args.from_csv)
        if not csv_path.is_absolute():
            csv_path = root / csv_path
        with csv_path.open(encoding="utf-8-sig") as fp:
            rows = list(csv.DictReader(fp))
        codes: list[str] = []
        for row in rows:
            row_market = Market(row.get("market", market.value))
            if row_market != market and args.market:
                continue
            codes.append(normalize_stock_code(row["code"], row_market))
        return codes
    raise SystemExit("请指定 --codes 或 --from-csv")


if __name__ == "__main__":
    raise SystemExit(main())
