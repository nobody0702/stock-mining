#!/usr/bin/env python3
"""Apply business_model batch scores: not_interested (<4) + review candidates (>=4)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _bootstrap_env(root: Path) -> None:
    from stock_mining.utils import load_project_env

    load_project_env(root / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="商业模式 triage：低分进 not_interested，高分进 review")
    parser.add_argument(
        "--results-dir",
        default="agent_working/results",
        help="商业模式 batch_*.md 目录",
    )
    parser.add_argument(
        "--candidates",
        default="data/results/normal_value_candidates.json",
        help="量化候选 JSON（按 code 关联）",
    )
    parser.add_argument(
        "--review-json",
        default="data/results/normal_value_review.json",
        help="商业模式≥4 子集，供 serve_review 的「正常估值·商业模式≥4」",
    )
    parser.add_argument(
        "--dispositions-dir",
        default="data/state/dispositions",
    )
    parser.add_argument(
        "--min-pass-score",
        type=int,
        default=4,
    )
    parser.add_argument(
        "--suppress-days",
        type=int,
        default=183,
        help="not_interested release_at = now + N 天（默认约半年）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _bootstrap_env(root)

    from stock_mining.llm.business_model_batch import load_candidates
    from stock_mining.llm.business_model_results import load_business_model_scores
    from stock_mining.models import CandidateHit
    from stock_mining.pipeline.candidate_index import index_by_code, lookup_by_code
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.state.store import UserStateStore

    scores = load_business_model_scores(root / args.results_dir)
    hits = load_candidates(root / args.candidates)
    by_code = index_by_code(hits)

    now = datetime.now()
    release_at = now + timedelta(days=args.suppress_days)

    fail_codes: list[str] = []
    pass_hits: list[CandidateHit] = []
    unmatched: list[str] = []

    for code, row in sorted(scores.items()):
        hit = lookup_by_code(hits, code)
        if hit is None:
            unmatched.append(code)
            continue
        if row.score < args.min_pass_score:
            fail_codes.append(code)
        else:
            pass_hits.append(hit)

    store = UserStateStore(
        root / "data/state/user_state.sqlite3",
        dispositions_dir=root / args.dispositions_dir,
    )

    if args.dry_run:
        print(f"商业模式评分: {len(scores)} 只")
        print(f"关联候选 (by code): {len(scores) - len(unmatched)} 只")
        print(f"not_interested (<{args.min_pass_score}): {len(fail_codes)} 只")
        print(f"review (>={args.min_pass_score}): {len(pass_hits)} 只")
        if unmatched:
            print(f"未匹配 code: {unmatched}")
        return 0

    for code in fail_codes:
        hit = by_code[code]
        row = scores[code]
        store.set_stock_disposition(
            hit.stock_key,
            row.name or hit.name,
            hit.market.value,
            DispositionKind.NOT_INTERESTED,
            release_at=release_at,
            now=now,
        )

    for hit in pass_hits:
        store.clear_stock_disposition(hit.stock_key)

    review_payload = {
        "strategy": "normal_value_bm_pass",
        "source": "normal_value_business_model_pass",
        "business_model_min_score": args.min_pass_score,
        "generated_at": now.isoformat(),
        "run_at": now.isoformat(timespec="seconds"),
        "top_n": None,
        "count": len(pass_hits),
        "candidates": [hit.to_dict() for hit in pass_hits],
    }
    review_path = root / args.review_json
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"not_interested 已更新 {len(fail_codes)} 只，release_at={release_at.date()}")
    print(f"review 候选已写入 {review_path}（{len(pass_hits)} 只）")
    if unmatched:
        print(f"警告: 未匹配 code: {unmatched}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
