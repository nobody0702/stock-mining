#!/usr/bin/env python3
"""Split normal_value candidates into batches and score business_model dimension."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _bootstrap_env(root: Path) -> None:
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="223 只 normal_value 候选股 · 商业模式分批打分")
    parser.add_argument(
        "command",
        choices=["prepare", "run", "merge"],
        help="prepare=拆分批次; run=调用 LLM 打分; merge=合并 MD",
    )
    parser.add_argument(
        "--candidates",
        default="data/results/normal_value_candidates.json",
    )
    parser.add_argument(
        "--working-dir",
        default="agent_working",
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
        "--batch",
        type=int,
        default=None,
        help="run 时指定批次号 1-11；省略则跑全部",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只写 prompt，不调用 API",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _bootstrap_env(root)

    from stock_mining.llm.business_model_batch import (
        NUM_BATCHES,
        SYSTEM_PROMPT,
        build_business_model_batch_prompt,
        format_batch_result_markdown,
        get_business_model_dimension,
        load_batch,
        load_candidates,
        merge_batch_markdowns,
        parse_business_model_batch_table,
        save_batch_manifest,
    )
    from stock_mining.llm.dimensions import load_dimensions_config
    from stock_mining.llm.jiquer_client import JiquerAPIError, JiquerAuthError
    from stock_mining.llm.llm_config import build_jiquer_client, load_llm_config

    working_dir = root / args.working_dir
    candidates_path = root / args.candidates
    dimensions_config = load_dimensions_config(root / args.dimensions)
    dimension = get_business_model_dimension(dimensions_config)
    results_dir = working_dir / "results"
    prompts_dir = working_dir / "prompts"

    if args.command == "prepare":
        hits = load_candidates(candidates_path)
        paths = save_batch_manifest(hits, working_dir, num_batches=NUM_BATCHES)
        print(f"已写入 {working_dir / 'stock_list.json'}（{len(hits)} 只）")
        print(f"已拆分 {len(paths)} 批（目标 {NUM_BATCHES} 批）")
        return 0

    if args.command == "merge":
        results_dir.mkdir(parents=True, exist_ok=True)
        batch_files = sorted(results_dir.glob("batch_*.md"))
        if not batch_files:
            print("未找到 results/batch_*.md，请先 run", file=sys.stderr)
            return 1
        merged = merge_batch_markdowns(
            batch_files,
            title="正常估值候选股 · 商业模式打分（223 只）",
        )
        out_path = working_dir / "business_model_scores.md"
        out_path.write_text(merged, encoding="utf-8")
        print(f"已合并 → {out_path}（{len(batch_files)} 批）")
        return 0

    # run
    batches_dir = working_dir / "batches"
    if not batches_dir.exists():
        print("请先运行 prepare", file=sys.stderr)
        return 1

    batch_paths = sorted(batches_dir.glob("batch_*.json"))
    if args.batch is not None:
        target = batches_dir / f"batch_{args.batch:02d}.json"
        if not target.exists():
            print(f"批次不存在: {target}", file=sys.stderr)
            return 1
        batch_paths = [target]

    results_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    llm_cfg = load_llm_config(root / args.llm_config)
    if not args.dry_run:
        llm_cfg.jiquer.timeout_sec = max(float(llm_cfg.jiquer.timeout_sec), 300.0)
    client = None if args.dry_run else build_jiquer_client(llm_cfg)

    for batch_path in batch_paths:
        batch_no, hits = load_batch(batch_path)
        prompt = build_business_model_batch_prompt(
            hits,
            dimension,
            include_quant_summary=dimensions_config.include_quant_summary,
        )
        prompt_path = prompts_dir / f"batch_{batch_no:02d}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"[batch {batch_no:02d}] {len(hits)} 只 · prompt → {prompt_path}")

        if args.dry_run:
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
            return 1

        elapsed = time.monotonic() - t0
        parsed_rows = parse_business_model_batch_table(response.content)
        md = format_batch_result_markdown(
            batch_no,
            hits,
            parsed_rows,
            raw_response=response.content,
        )
        out_path = results_dir / f"batch_{batch_no:02d}.md"
        out_path.write_text(md, encoding="utf-8")
        print(
            f"[batch {batch_no:02d}] 解析 {len(parsed_rows)}/{len(hits)} 行 · "
            f"{elapsed:.1f}s → {out_path}"
        )
        time.sleep(1)

    if not args.dry_run and args.batch is None:
        merged = merge_batch_markdowns(
            sorted(results_dir.glob("batch_*.md")),
            title="正常估值候选股 · 商业模式打分（223 只）",
        )
        out_path = working_dir / "business_model_scores.md"
        out_path.write_text(merged, encoding="utf-8")
        print(f"已合并 → {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
