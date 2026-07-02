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
        choices=["a", "h", "hk", "u"],
        default="a",
        help="市场：a=A股, h=港股, u=美股(预留)",
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
    from stock_mining.markets.base import Market, normalize_stock_code, parse_market
    from stock_mining.markets.stock_key import parse_stock_key
    from stock_mining.models import StockInfo
    from stock_mining.pipeline.screener import DailyScreener

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    screener = DailyScreener.from_yaml(config_path, state_store=None)
    market = parse_market(args.market)
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
        from stock_mining.markets.stock_key import parse_stock_input

        codes: list[str] = []
        for token in args.codes:
            token_market, bare = parse_stock_input(token, default_market=market)
            if token_market != market:
                continue
            codes.append(bare)
        return codes
    if args.from_csv:
        csv_path = Path(args.from_csv)
        if not csv_path.is_absolute():
            csv_path = root / csv_path
        with csv_path.open(encoding="utf-8-sig") as fp:
            rows = list(csv.DictReader(fp))
        codes = []
        for row in rows:
            raw_code = row["code"]
            if ":" in raw_code:
                row_market, bare = parse_stock_key(raw_code)
            else:
                row_market = parse_market(row.get("market", market.value))
                bare = normalize_stock_code(raw_code, row_market)
            if row_market != market:
                continue
            codes.append(bare)
        return codes
    raise SystemExit("请指定 --codes 或 --from-csv")


if __name__ == "__main__":
    raise SystemExit(main())
