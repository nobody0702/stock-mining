#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily A/HK stock screener")
    parser.add_argument(
        "-c",
        "--config",
        default="config/screen.yaml",
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
    parser.add_argument(
        "--markets",
        nargs="+",
        choices=["a", "hk"],
        default=None,
        help="Markets to screen",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override output top_n",
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip blacklist/cooldown filtering",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.config import load_pipeline_config, resolve_project_path
    from stock_mining.markets.base import Market
    from stock_mining.pipeline.screener import DailyScreener
    from stock_mining.state.store import UserStateStore

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    config = load_pipeline_config(config_path)
    state_store = None if args.skip_dedup else UserStateStore(
        resolve_project_path(config_path, config.state.db_path),
        dispositions_dir=resolve_project_path(config_path, config.state.dispositions_dir),
    )
    screener = DailyScreener.from_yaml(config_path, state_store=state_store)

    if args.max_stocks is not None:
        screener.config.universe.max_stocks = args.max_stocks
    if args.codes:
        screener.config.universe.codes = args.codes
    if args.markets:
        screener.config.markets = [Market(item) for item in args.markets]
        from stock_mining.markets.providers import build_market_providers

        screener.providers = build_market_providers(
            screener.config.data_source,
            screener.config.markets,
            use_cache=screener.config.fetch.use_cache,
            cache_dir=screener.config.fetch.cache_dir,
            cache_ttl_hours=screener.config.fetch.cache_ttl_hours,
            request_interval_sec=screener.config.fetch.request_interval_sec,
        )
    if args.top_n is not None:
        screener.config.output.top_n = args.top_n

    hits = screener.run()
    json_path, csv_path, legacy_path = screener.save(hits)

    print(f"命中 {len(hits)} 只")
    for hit in hits:
        print(f"{hit.market.value}:{hit.code}\t{hit.name}\t{hit.track}\t{hit.score:.1f}")
    print(f"已写入: {json_path}")
    print(f"已写入: {csv_path}")
    print(f"已写入: {legacy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
