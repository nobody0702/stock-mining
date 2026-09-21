#!/usr/bin/env python3
"""Score undisposed A-shares on business_model + moat in batches of 10.

Workflow::

    cd stock-mining && source .venv/bin/activate
    # needs config/llm.yaml + .env (same as run_business_model_batches)

    python3 scripts/run_undisposed_bm_moat_batches.py prepare
    python3 scripts/run_undisposed_bm_moat_batches.py run --dry-run --batch 1
    python3 scripts/run_undisposed_bm_moat_batches.py run
    python3 scripts/run_undisposed_bm_moat_batches.py merge

    # or all-in-one:
    python3 scripts/run_undisposed_bm_moat_batches.py all

Working dir: agent_working/undisposed_bm_moat/
  stock_list.json  batches/  prompts/  results/  status.json  bm_moat_scores.md
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def _bootstrap(root: Path) -> None:
    sys.path.insert(0, str(root))
    os.chdir(root)
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def _working_dir(root: Path, relative: str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else root / path


def cmd_prepare(root: Path, args: argparse.Namespace) -> int:
    from stock_mining.data.akshare_provider import AkshareDataProvider
    from stock_mining.llm.undisposed_bm_moat_batch import (
        BATCH_SIZE,
        filter_undisposed_a_shares,
        load_disposed_stock_keys,
        save_undisposed_batches,
        stocks_to_hits,
    )

    working_dir = _working_dir(root, args.working_dir)
    dispositions_dir = Path(args.dispositions_dir)
    if not dispositions_dir.is_absolute():
        dispositions_dir = root / dispositions_dir

    print("拉取 A 股全市场列表…")
    provider = AkshareDataProvider(
        use_cache=not args.no_cache,
        cache_dir=str(root / args.cache_dir),
    )
    universe = provider.list_stocks()
    disposed = load_disposed_stock_keys(dispositions_dir)
    remaining = filter_undisposed_a_shares(universe, disposed)
    if args.limit is not None:
        remaining = remaining[: max(0, args.limit)]

    hits = stocks_to_hits(remaining)
    batch_size = args.batch_size or BATCH_SIZE
    paths = save_undisposed_batches(
        hits,
        working_dir,
        batch_size=batch_size,
        meta={
            "universe_size": len(universe),
            "disposed": len(disposed),
        },
    )
    print(
        f"universe={len(universe)} disposed_keys={len(disposed)} "
        f"remaining={len(hits)} batches={len(paths)} → {working_dir}"
    )
    return 0


def cmd_run(root: Path, args: argparse.Namespace) -> int:
    from stock_mining.llm.dimensions import load_dimensions_config
    from stock_mining.llm.jiquer_client import JiquerAPIError, JiquerAuthError
    from stock_mining.llm.llm_config import build_jiquer_client, load_llm_config
    from stock_mining.llm.undisposed_bm_moat_batch import (
        SYSTEM_PROMPT,
        build_bm_moat_batch_prompt,
        format_bm_moat_batch_markdown,
        get_dimension,
        load_batch,
        mark_batch_completed,
        merge_bm_moat_results,
        read_status,
        write_status,
    )

    working_dir = _working_dir(root, args.working_dir)
    batches_dir = working_dir / "batches"
    if not batches_dir.is_dir():
        print("请先运行 prepare", file=sys.stderr)
        return 1

    batch_paths = sorted(batches_dir.glob("batch_*.json"))
    if args.batch is not None:
        target = batches_dir / f"batch_{args.batch:02d}.json"
        if not target.exists():
            print(f"批次不存在: {target}", file=sys.stderr)
            return 1
        batch_paths = [target]

    dimensions_config = load_dimensions_config(root / args.dimensions)
    business_model = get_dimension(dimensions_config, "business_model")
    moat = get_dimension(dimensions_config, "moat")

    results_dir = working_dir / "results"
    prompts_dir = working_dir / "prompts"
    results_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    llm_cfg = load_llm_config(root / args.llm_config)
    if not args.dry_run:
        llm_cfg.jiquer.timeout_sec = max(float(llm_cfg.jiquer.timeout_sec), 300.0)
    client = None if args.dry_run else build_jiquer_client(llm_cfg)

    for batch_path in batch_paths:
        batch_no, hits = load_batch(batch_path)
        prompt = build_bm_moat_batch_prompt(hits, business_model, moat)
        prompt_path = prompts_dir / f"batch_{batch_no:02d}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"[batch {batch_no:02d}] {len(hits)} 只 · prompt → {prompt_path}")

        if args.dry_run:
            mark_batch_completed(working_dir, batch_no)
            continue

        assert client is not None
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        t0 = time.monotonic()
        try:
            response = client.chat(messages, thinking=False, web_search=False)
        except (JiquerAuthError, JiquerAPIError) as exc:
            print(f"[batch {batch_no:02d}] API 失败: {exc}", file=sys.stderr)
            status = read_status(working_dir)
            status["phase"] = "error"
            status["last_error"] = str(exc)
            status["updated_at"] = datetime.now().isoformat(timespec="seconds")
            write_status(working_dir, status)
            return 1

        elapsed = time.monotonic() - t0
        from stock_mining.llm.undisposed_bm_moat_batch import parse_bm_moat_batch_table

        parsed_rows = parse_bm_moat_batch_table(response.content)
        md = format_bm_moat_batch_markdown(
            batch_no,
            hits,
            parsed_rows,
            raw_response=response.content,
        )
        out_path = results_dir / f"batch_{batch_no:02d}.md"
        out_path.write_text(md, encoding="utf-8")
        mark_batch_completed(working_dir, batch_no)
        print(
            f"[batch {batch_no:02d}] 解析 {len(parsed_rows)}/{len(hits)} 行 · "
            f"{elapsed:.1f}s → {out_path}"
        )
        time.sleep(1)

    if not args.dry_run and args.batch is None:
        merged = merge_bm_moat_results(
            results_dir,
            title="未处置 A 股 · 商业模式+护城河打分",
        )
        out_path = working_dir / "bm_moat_scores.md"
        out_path.write_text(merged, encoding="utf-8")
        status = read_status(working_dir)
        status["phase"] = "merged"
        status["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_status(working_dir, status)
        print(f"已合并 → {out_path}")

    return 0


def cmd_merge(root: Path, args: argparse.Namespace) -> int:
    from stock_mining.llm.undisposed_bm_moat_batch import merge_bm_moat_results, read_status, write_status

    working_dir = _working_dir(root, args.working_dir)
    results_dir = working_dir / "results"
    batch_files = sorted(results_dir.glob("batch_*.md"))
    if not batch_files:
        print("未找到 results/batch_*.md，请先 run", file=sys.stderr)
        return 1
    merged = merge_bm_moat_results(
        results_dir,
        title="未处置 A 股 · 商业模式+护城河打分",
    )
    out_path = working_dir / "bm_moat_scores.md"
    out_path.write_text(merged, encoding="utf-8")
    status = read_status(working_dir)
    status["phase"] = "merged"
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_status(working_dir, status)
    print(f"已合并 → {out_path}（{len(batch_files)} 批）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="未处置 A 股 · 商业模式+护城河分批打分（每批 10 只）",
    )
    parser.add_argument(
        "command",
        choices=["prepare", "run", "merge", "all"],
        help="prepare=差集拆批; run=LLM打分; merge=合并; all=三者顺序执行",
    )
    parser.add_argument(
        "--working-dir",
        default="agent_working/undisposed_bm_moat",
        help="中间状态与结果目录",
    )
    parser.add_argument(
        "--dispositions-dir",
        default="data/state/dispositions",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/cache",
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
        "--batch-size",
        type=int,
        default=10,
        help="prepare 时每批股票数（默认 10）",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=None,
        help="run 时只跑指定批次号",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="prepare 时仅保留差集前 N 只（试跑）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run 时只写 prompt，不调 API",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    _bootstrap(root)

    if args.command == "prepare":
        return cmd_prepare(root, args)
    if args.command == "run":
        return cmd_run(root, args)
    if args.command == "merge":
        return cmd_merge(root, args)

    # all
    code = cmd_prepare(root, args)
    if code != 0:
        return code
    code = cmd_run(root, args)
    if code != 0:
        return code
    if args.dry_run:
        print("dry-run：跳过 merge（尚无 results）")
        return 0
    return cmd_merge(root, args)


if __name__ == "__main__":
    raise SystemExit(main())
