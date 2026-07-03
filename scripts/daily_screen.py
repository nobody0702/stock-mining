#!/usr/bin/env python3
"""Daily multi-market stock screener."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


HELP_EPILOG = """
策略 (--strategy)
  mispriced_growth      被错杀的白马股（A 股，config/screen.yaml）
  normal_value          正常估值不下滑（A 股）
  mispriced_growth_hk   港股通·被错杀的白马股
  all                   以上三个策略都跑，并合并写入 all_candidates.json
  支持逗号组合，如 mispriced_growth,normal_value（同市场只拉一次数据）

市场 (--market)
  a     只跑 A 股相关策略
  h     只跑港股策略（hk 为别名）
  u     美股（预留，当前无数据）
  all   A 股 + 港股
  支持逗号组合，如 a,h

示例
  python3 scripts/daily_screen.py --strategy all --market all
  python3 scripts/daily_screen.py --strategy mispriced_growth,normal_value --market a
  python3 scripts/daily_screen.py --strategy normal_value --market a
  python3 scripts/daily_screen.py --strategy mispriced_growth_hk --market h
  python3 scripts/daily_screen.py --strategy mispriced_growth --codes a:600519 h:00700 --market all
  python3 scripts/daily_screen.py --strategy all --market a --skip-dedup --max-stocks 100

股票代码请带市场前缀 a:/h:/u:，避免 A/H 撞码（如 a:000001 与 h:00001）。
"""


def _bootstrap_env(root: Path) -> None:
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def _build_parser() -> argparse.ArgumentParser:
    from stock_mining.markets.market_scope import format_market_scope_help
    from stock_mining.strategies import MINING_STRATEGIES

    strategy_help = ", ".join(
        f"{item.id}={item.label}" for item in MINING_STRATEGIES.values()
    ) + ", all=全部策略（支持逗号组合）"
    parser = argparse.ArgumentParser(
        description="量化挖掘：被错杀的白马股 / 正常估值不下滑 / 港股通",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument(
        "--strategy",
        default="mispriced_growth",
        help=strategy_help,
    )
    parser.add_argument(
        "--market",
        default="all",
        help=format_market_scope_help(),
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="自定义 YAML（仅对单个策略生效，覆盖默认配置）",
    )
    parser.add_argument("--max-stocks", type=int, default=None, help="调试：限制 universe 数量")
    parser.add_argument(
        "--codes",
        nargs="+",
        default=None,
        help="只筛指定代码，推荐 a:600519 h:00700",
    )
    parser.add_argument("--top-n", type=int, default=None, help="只保留分数最高的 N 只")
    parser.add_argument("--skip-dedup", action="store_true", help="跳过 dispositions 过滤")
    return parser


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _bootstrap_env(root)

    from stock_mining.config import load_pipeline_config, resolve_project_path
    from stock_mining.markets.market_scope import parse_market_selection
    from stock_mining.pipeline.multi_screen import run_mining
    from stock_mining.state.store import UserStateStore
    from stock_mining.strategies import MINING_STRATEGIES, parse_strategy_selection, resolve_config_path

    parser = _build_parser()
    args = parser.parse_args()

    try:
        job_ids = parse_strategy_selection(args.strategy)
        selected_markets = parse_market_selection(args.market)
    except ValueError as exc:
        parser.error(str(exc))

    if args.config and len(job_ids) > 1:
        parser.error("--config 仅支持单个策略，不能与逗号组合或 all 同时使用")

    config_path = None
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = root / config_path
    elif len(job_ids) == 1:
        config_path = resolve_config_path(root, job_ids[0])

    state_store = None
    if not args.skip_dedup and config_path is not None:
        cfg = load_pipeline_config(config_path)
        state_store = UserStateStore(
            resolve_project_path(config_path, cfg.state.db_path),
            dispositions_dir=resolve_project_path(config_path, cfg.state.dispositions_dir),
        )
    elif not args.skip_dedup:
        cfg = load_pipeline_config(resolve_config_path(root, "mispriced_growth"))
        base = resolve_config_path(root, "mispriced_growth")
        state_store = UserStateStore(
            resolve_project_path(base, cfg.state.db_path),
            dispositions_dir=resolve_project_path(base, cfg.state.dispositions_dir),
        )

    results = run_mining(
        root,
        strategy_id=args.strategy,
        selected_markets=selected_markets,
        state_store=state_store,
        max_stocks=args.max_stocks,
        codes=args.codes,
        top_n=args.top_n,
        config_override=config_path if len(job_ids) == 1 else None,
    )

    if not results:
        print(f"策略 {args.strategy} 在 market={args.market} 下无可运行任务")
        return 0

    print(f"市场范围: {args.market}")
    total = 0
    for result in results:
        total += len(result.hits)
        print(f"\n== {result.strategy_label} ({result.strategy_id}) ==")
        print(f"市场: {', '.join(m.value for m in result.markets)}")
        print(f"命中 {len(result.hits)} 只")
        for hit in result.hits[:20]:
            print(f"{hit.stock_key}\t{hit.name}\t{hit.track}\t{hit.score:.1f}")
        if len(result.hits) > 20:
            print(f"... 另有 {len(result.hits) - 20} 只")
        print(f"已写入: {result.json_path}")
        print(f"已写入: {result.csv_path}")

    if set(job_ids) == set(MINING_STRATEGIES.keys()):
        print(f"\n合并总计 {total} 只 → data/results/all_candidates.json")

    if len(job_ids) == 1:
        review_cmd = f"python3 scripts/serve_review.py --strategy {job_ids[0]}"
    else:
        review_cmd = "python3 scripts/serve_review.py"
    print(f"\n下一步：运行 {review_cmd} 打开审阅页，在网页中手工筛选、标记候选股")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
