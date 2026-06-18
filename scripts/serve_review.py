#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def resolve_python(root: Path) -> str:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    app_path = root / "stock_mining" / "web" / "review_app.py"
    python = resolve_python(root)
    cmd = [python, "-m", "streamlit", "run", str(app_path)]
    try:
        return subprocess.call(cmd, cwd=root)
    except FileNotFoundError:
        print("未找到 streamlit。请先安装依赖：")
        print(f"  cd {root}")
        print("  python3 -m venv .venv && source .venv/bin/activate")
        print("  pip install -r requirements.txt")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
