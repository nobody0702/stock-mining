from __future__ import annotations

import argparse

import pytest

from stock_mining.utils import copy_to_clipboard


def test_copy_to_clipboard_darwin(monkeypatch):
    captured: dict[str, bytes] = {}

    def fake_run(cmd, *, input, check):  # noqa: A002
        assert cmd == ["pbcopy"]
        captured["data"] = input

    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("stock_mining.utils.subprocess.run", fake_run)

    ok, err = copy_to_clipboard("hello prompt")
    assert ok is True
    assert err is None
    assert captured["data"] == b"hello prompt"


def test_copy_to_clipboard_unsupported(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "FreeBSD")
    ok, err = copy_to_clipboard("x")
    assert ok is False
    assert err is not None


def test_print_prompt_default_copy_on_darwin_tty(monkeypatch):
    from scripts.print_prompt import _default_copy_to_clipboard, resolve_screen_config

    assert resolve_screen_config("h", "config/screen.yaml") == "config/screen_hk.yaml"
    assert resolve_screen_config("a", "config/screen.yaml") == "config/screen.yaml"
    assert resolve_screen_config("h", "config/custom.yaml") == "config/custom.yaml"

    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    args = argparse.Namespace(copy=False, no_copy=False, output=None)
    assert _default_copy_to_clipboard(args) is True

    args_no_copy = argparse.Namespace(copy=False, no_copy=True, output=None)
    assert _default_copy_to_clipboard(args_no_copy) is False

    args_output = argparse.Namespace(copy=False, no_copy=False, output="out.md")
    assert _default_copy_to_clipboard(args_output) is False
