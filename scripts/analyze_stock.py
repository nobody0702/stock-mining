#!/usr/bin/env python3
"""Analyze stocks via jiquer DeepSeek API and print Markdown score tables."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _bootstrap_env(root: Path) -> None:
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="输入股票代码或名称，调用 DeepSeek 分析并输出 Markdown 表格",
    )
    parser.add_argument(
        "stocks",
        nargs="*",
        help="股票代码或名称，可多个；亦可用 @codes.txt",
    )
    parser.add_argument(
        "--market",
        choices=["a", "hk"],
        default="a",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config/screen.yaml",
        help="筛选/拉数配置",
    )
    parser.add_argument(
        "--dimensions",
        default="config/analysis_dimensions.yaml",
    )
    parser.add_argument(
        "--llm-config",
        default="config/llm.yaml",
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="尝试开启深度思考（best-effort，取决于代理是否透传）",
    )
    parser.add_argument(
        "--web-search",
        action="store_true",
        help="自动搜集公告与网络检索摘要，注入 prompt 后再分析",
    )
    parser.add_argument(
        "--show-reasoning",
        action="store_true",
        help="将思维链输出到 stderr",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只生成 prompt，不调用 API",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="探测 API 连通性与是否返回 reasoning_content",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
    )
    parser.add_argument(
        "--full-fetch",
        action="store_true",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _bootstrap_env(root)

    from stock_mining.llm.dimensions import load_dimensions_config
    from stock_mining.llm.jiquer_client import JiquerAPIError, JiquerAuthError
    from stock_mining.llm.llm_config import build_jiquer_client, load_llm_config
    from stock_mining.llm.stock_analyzer import analyze_stock, format_result_table
    from stock_mining.llm.stock_resolver import StockResolveError, resolve_stock_inputs
    from stock_mining.llm.web_context import build_web_context
    from stock_mining.markets.base import Market
    from stock_mining.pipeline.single_stock import build_live_stock_prompt, load_live_screener

    llm_cfg = load_llm_config(root / args.llm_config)
    client = build_jiquer_client(llm_cfg)

    if args.probe:
        return _run_probe(client)

    if not args.stocks:
        parser.error("请提供股票代码/名称，或使用 --probe")

    thinking = args.thinking or llm_cfg.jiquer.thinking_enabled_by_default
    web_search = (
        args.web_search
        or llm_cfg.web_context.enabled_by_default
        or llm_cfg.jiquer.web_search_enabled_by_default
    )
    jiquer_native = llm_cfg.web_context.jiquer_native_search

    market = Market(args.market)
    config_path = root / args.config
    dimensions = load_dimensions_config(root / args.dimensions)
    use_cache = False if args.no_cache else None
    screener = load_live_screener(config_path, use_cache=use_cache)
    provider = screener.providers.get(market)
    if provider is None:
        print(f"配置未启用市场 {market.value}", file=sys.stderr)
        return 2

    try:
        resolved = resolve_stock_inputs(
            list(args.stocks),
            market=market,
            list_stocks_fn=provider.list_stocks,
        )
    except StockResolveError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    chunks: list[str] = []
    had_missing = False

    for item in resolved:
        def _progress(message: str) -> None:
            print(message, file=sys.stderr, flush=True)

        try:
            if args.dry_run:
                live = build_live_stock_prompt(
                    screener,
                    item.code,
                    item.market,
                    dimensions_config=dimensions,
                    require_hit=False,
                    fast_fetch=not args.full_fetch,
                    progress=_progress,
                )
                web_ctx = ""
                if web_search:
                    web_ctx = build_web_context(
                        item.code,
                        item.name,
                        config=llm_cfg.web_context,
                        progress=_progress,
                        on_warning=lambda msg: print(msg, file=sys.stderr, flush=True),
                    )
                chunks.append(f"# Prompt: {item.name}\n\n{live.prompt}{web_ctx}")
                continue

            web_ctx = ""
            if web_search:
                web_ctx = build_web_context(
                    item.code,
                    item.name,
                    config=llm_cfg.web_context,
                    progress=_progress,
                    on_warning=lambda msg: print(msg, file=sys.stderr, flush=True),
                )
                if not web_ctx.strip():
                    print(
                        f"提示: {item.name} 未搜集到联网上下文（公告/检索均为空）",
                        file=sys.stderr,
                    )

            result = analyze_stock(
                screener,
                item.code,
                item.market,
                dimensions_config=dimensions,
                client=client,
                thinking=thinking,
                web_search=web_search,
                jiquer_native_search=jiquer_native,
                web_context_text=web_ctx,
                fast_fetch=not args.full_fetch,
                progress=_progress,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except (JiquerAuthError, JiquerAPIError) as exc:
            print(str(exc), file=sys.stderr)
            return 3

        if thinking and not result.reasoning_content:
            print(
                f"提示: {item.code} 未返回 reasoning_content，代理可能未开启深度思考",
                file=sys.stderr,
            )
        if args.show_reasoning and result.reasoning_content:
            print(f"\n--- reasoning: {item.name} ---\n{result.reasoning_content}\n", file=sys.stderr)

        if result.missing:
            had_missing = True
            print(
                f"警告: {item.name} 缺少维度: {', '.join(result.missing)}",
                file=sys.stderr,
            )

        chunks.append(format_result_table(result, dimensions))
        chunks.append("")

    text = "\n".join(chunks).rstrip() + "\n"
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"已写入: {out_path}", file=sys.stderr)
    else:
        print(text, end="")

    return 1 if had_missing else 0


def _run_probe(client) -> int:
    from stock_mining.llm.jiquer_client import JiquerAPIError, JiquerAuthError

    try:
        result = client.probe()
    except JiquerAuthError as exc:
        print(f"认证失败: {exc}", file=sys.stderr)
        return 3
    except JiquerAPIError as exc:
        print(f"API 失败: {exc}", file=sys.stderr)
        return 3

    print("API 探测成功", file=sys.stderr)
    print(f"  content: {result['content'][:80]!r}", file=sys.stderr)
    print(f"  has_reasoning_content: {result['has_reasoning_content']}", file=sys.stderr)
    if result["has_reasoning_content"]:
        print(f"  reasoning_preview: {result['reasoning_preview']!r}", file=sys.stderr)
    else:
        print(
            "  深度思考: 当前代理未返回 reasoning_content；可尝试换 model 或联系平台",
            file=sys.stderr,
        )
    print(f"  usage: {result['usage']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
