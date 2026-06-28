from __future__ import annotations

import os
from pathlib import Path

from stock_mining.utils import load_project_env


def test_load_project_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nJIQUER_API_KEY=test-key-from-file\nEMPTY=\n",
        encoding="utf-8",
    )
    os.environ.pop("JIQUER_API_KEY", None)
    assert load_project_env(env_file) is True
    assert os.environ["JIQUER_API_KEY"] == "test-key-from-file"


def test_load_project_env_does_not_override_existing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JIQUER_API_KEY=from-file\n", encoding="utf-8")
    os.environ["JIQUER_API_KEY"] = "from-shell"
    load_project_env(env_file)
    assert os.environ["JIQUER_API_KEY"] == "from-shell"
