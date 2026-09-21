#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def resolve_python(root: Path) -> str:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch the stock-mining review UI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--strategy",
        choices=[
            "mispriced_growth",
            "normal_value",
            "mispriced_growth_hk",
            "quality_roe_margin",
            "normal_value_bm_pass",
            "all",
        ],
        default=None,
        help="打开时默认选中的筛选策略（也可在侧边栏切换）",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址；本机使用 127.0.0.1")
    parser.add_argument("--port", type=int, default=8501, help="Web 端口")
    parser.add_argument("--no-headless", action="store_true", help="启动后尝试打开浏览器")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    app_path = root / "stock_mining" / "web" / "review_app.py"
    python = resolve_python(root)
    cmd = [
        python,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "false" if args.no_headless else "true",
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
    ]
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    if args.strategy:
        env["STOCK_MINING_REVIEW_STRATEGY"] = args.strategy
    try:
        return subprocess.call(cmd, cwd=root, env=env)
    except FileNotFoundError:
        print("未找到 streamlit。请先安装依赖：")
        print(f"  cd {root}")
        print("  python3 -m venv .venv && source .venv/bin/activate")
        print("  pip install -r requirements.txt")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
