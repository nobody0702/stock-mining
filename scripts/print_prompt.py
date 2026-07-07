#!/usr/bin/env python3
"""Print a live mining prompt for one stock to stdout (no web UI)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _default_copy_to_clipboard(args: argparse.Namespace) -> bool:
    if args.no_copy:
        return False
    if args.copy:
        return True
    if args.output is not None:
        return False
    if not sys.stdout.isatty():
        return False
    return sys.platform == "darwin"


DEFAULT_SCREEN_CONFIG = "config/screen.yaml"
HK_SCREEN_CONFIG = "config/screen_hk.yaml"


def resolve_screen_config(market_arg: str, config_arg: str) -> str:
    """Pick screen yaml: HK uses screen_hk.yaml when user kept the A-share default."""
    market = market_arg.lower()
    if market in {"h", "hk"} and config_arg.replace("\\", "/") == DEFAULT_SCREEN_CONFIG:
        return HK_SCREEN_CONFIG
    return config_arg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="输入股票代码，实时拉数并输出 Cursor 分析提示词（无需打开 Web）",
    )
    parser.add_argument("code", help="股票代码，如 603605 或 00700")
    parser.add_argument(
        "--market",
        choices=["a", "h", "hk", "u"],
        default="a",
        help="市场：a=A股, h=港股, u=美股(预留); hk 为 h 的别名",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_SCREEN_CONFIG,
        help="筛选配置路径（--market h 且未改此项时自动用 config/screen_hk.yaml）",
    )
    parser.add_argument(
        "--dimensions",
        default="config/analysis_dimensions.yaml",
        help="分析维度配置路径",
    )
    parser.add_argument(
        "--require-hit",
        action="store_true",
        help="仅当股票通过 screen.yaml 筛选时才输出（否则退出码 2）",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="跳过 AkShare 本地缓存，强制重新拉取",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="写入文件路径（默认打印到 stdout）",
    )
    parser.add_argument(
        "--full-fetch",
        action="store_true",
        help="完整拉数（含 52 周高低点、股息等，较慢；默认走快速路径）",
    )
    parser.add_argument(
        "--meta",
        action="store_true",
        help="在提示词前打印一行元信息（代码、是否过筛选、轨道）",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="生成后将 prompt 写入系统剪贴板（macOS 交互终端下默认开启）",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="不写入剪贴板（关闭 macOS 交互终端下的默认复制）",
    )
    args = parser.parse_args()
    args.config = resolve_screen_config(args.market, args.config)

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.llm.dimensions import load_dimensions_config
    from stock_mining.markets.base import Market, parse_market
    from stock_mining.pipeline.single_stock import (
        ScreenMissError,
        build_live_stock_prompt,
        load_live_screener,
    )
    from stock_mining.utils import copy_to_clipboard

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path

    dimensions_path = Path(args.dimensions)
    if not dimensions_path.is_absolute():
        dimensions_path = root / dimensions_path

    market = parse_market(args.market)
    use_cache = False if args.no_cache else None

    try:
        screener = load_live_screener(config_path, use_cache=use_cache)

        def _progress(message: str) -> None:
            print(message, file=sys.stderr, flush=True)

        if args.market.lower() in {"h", "hk"} and config_path.name == "screen_hk.yaml":
            _progress(f"使用港股配置: {config_path.relative_to(root)}")

        result = build_live_stock_prompt(
            screener,
            args.code,
            market,
            dimensions_config=load_dimensions_config(dimensions_path),
            require_hit=args.require_hit,
            fast_fetch=not args.full_fetch,
            progress=_progress,
        )
    except ScreenMissError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    lines: list[str] = []
    if args.meta:
        track = result.matched_track or "未通过筛选"
        status = "通过" if result.passed_screen else "未通过"
        lines.append(
            f"# {result.hit.name} ({result.hit.market.value.upper()}:{result.hit.code}) "
            f"筛选:{status} 轨道:{track} 分数:{result.hit.score:.1f}"
        )
        lines.append("")
    lines.append(result.prompt)
    text = "\n".join(lines)

    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"已写入: {out_path}", file=sys.stderr)
    else:
        print(text)

    if _default_copy_to_clipboard(args):
        ok, err = copy_to_clipboard(text)
        if ok:
            print("已复制 prompt 到剪贴板，可直接 ⌘V 粘贴", file=sys.stderr)
        else:
            print(f"复制到剪贴板失败: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
