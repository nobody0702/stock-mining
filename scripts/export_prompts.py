#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Cursor prompts for candidates")
    parser.add_argument(
        "-c",
        "--config",
        default="config/screen.yaml",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max stocks in batch prompt",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)

    from stock_mining.web.review_service import ReviewService

    service = ReviewService.from_project_root(root)
    candidates = service.load_candidates()[: args.limit]
    if not candidates:
        print("暂无候选，请先运行 daily_screen.py")
        return 1

    prompt = service.build_batch_prompt(candidates)
    out_dir = root / "data" / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date.today().isoformat()}_batch.md"
    out_path.write_text(prompt, encoding="utf-8")
    print(f"已导出: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
