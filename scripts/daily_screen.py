#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily A-share stock screener")
    parser.add_argument(
        "-c",
        "--config",
        default="config/daily_screen.yaml",
        help="YAML config path",
    )
    parser.add_argument(
        "--max-stocks",
        type=int,
        default=None,
        help="Limit universe size for debugging",
    )
    parser.add_argument(
        "--codes",
        nargs="+",
        default=None,
        help="Only screen specific codes",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.pipeline.screener import DailyScreener

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    screener = DailyScreener.from_yaml(config_path)
    if args.max_stocks is not None:
        screener.config.universe.max_stocks = args.max_stocks
    if args.codes:
        screener.config.universe.codes = args.codes

    hits = screener.run()
    output_path = screener.save(hits)

    print(f"命中 {len(hits)} 只")
    for hit in hits:
        print(f"{hit.code}\t{hit.name}")
    print(f"已写入: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
