#!/usr/bin/env python3
"""Extend release_at on disposition JSON files (one-off maintenance)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def extend_release_at(
    dispositions_dir: Path,
    *,
    days_after_set_at: int,
    kinds: tuple[str, ...] = ("not_interested", "too_expensive"),
) -> int:
    updated = 0
    for kind in kinds:
        path = dispositions_dir / f"{kind}.json"
        if not path.exists():
            continue
        entries = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for entry in entries:
            set_at_raw = entry.get("set_at")
            if not set_at_raw:
                continue
            set_at = datetime.fromisoformat(str(set_at_raw))
            release_at = set_at + timedelta(days=days_after_set_at)
            new_value = release_at.isoformat()
            if entry.get("release_at") != new_value:
                entry["release_at"] = new_value
                updated += 1
                changed = True
        if changed:
            path.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="批量调整 dispositions 的 release_at")
    parser.add_argument(
        "--dispositions-dir",
        default="data/state/dispositions",
        help="dispositions JSON 目录",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="release_at = set_at + N 天（默认 365=一年）",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    dispositions_dir = Path(args.dispositions_dir)
    if not dispositions_dir.is_absolute():
        dispositions_dir = root / dispositions_dir

    count = extend_release_at(dispositions_dir, days_after_set_at=args.days)
    print(f"已更新 {count} 条 release_at（set_at + {args.days} 天）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
