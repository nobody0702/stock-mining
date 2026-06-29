#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def _bootstrap_env(root: Path) -> None:
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


STRATEGY_IDS = ("mispriced_growth", "normal_value", "mispriced_growth_hk")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily A/HK stock screener")
    parser.add_argument(
        "--strategy",
        choices=STRATEGY_IDS,
        default="mispriced_growth",
        help="筛选策略：mispriced_growth=错杀成长白马(A/HK可配)，"
        "normal_value=正常估值不下滑(A)，mispriced_growth_hk=港股通错杀成长",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="YAML config path（指定后覆盖 --strategy 默认配置）",
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
    from stock_mining.strategies import get_strategy, resolve_config_path

    strategy = get_strategy(args.strategy)
    config_path = resolve_config_path(root, args.strategy)
    if args.config:
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

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["strategy"] = strategy.id
    payload["run_at"] = datetime.now().isoformat(timespec="seconds")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"策略: {strategy.label} ({strategy.config_path})")
    print(f"命中 {len(hits)} 只")
    for hit in hits:
        print(f"{hit.market.value}:{hit.code}\t{hit.name}\t{hit.track}\t{hit.score:.1f}")
    print(f"已写入: {json_path}")
    print(f"已写入: {csv_path}")
    print(f"已写入: {legacy_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
