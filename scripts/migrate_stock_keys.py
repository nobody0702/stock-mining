#!/usr/bin/env python3
"""Migrate disposition stock_key from legacy hk: to h:."""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from stock_mining.markets.tags import normalize_legacy_stock_key


def migrate_file(path: Path) -> int:
    if not path.exists():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for row in rows:
        old = str(row.get("stock_key", ""))
        new = normalize_legacy_stock_key(old)
        if old != new:
            row["stock_key"] = new
            market = new.split(":", 1)[0]
            row["market"] = market
            changed += 1
    if changed:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    disp_dir = root / "data" / "state" / "dispositions"
    total = 0
    for name in ("not_interested.json", "too_expensive.json", "watchlist.json"):
        total += migrate_file(disp_dir / name)
    print(f"已迁移 {total} 条 stock_key → a:/h:/u: 格式")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
