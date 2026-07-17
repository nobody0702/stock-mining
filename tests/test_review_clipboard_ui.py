from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from stock_mining.markets.base import Market
from stock_mining.models import CandidateHit
from stock_mining.web.clipboard_button import (
    COPY_BUTTON_IFRAME_HEIGHT,
    build_copy_prompt_html,
    sanitize_dom_id,
)


def test_sanitize_dom_id_strips_unsafe_chars():
    assert sanitize_dom_id("prompt-copy-all-a:600519-tg-0") == "prompt_copy_all_a_600519_tg_0"
    assert sanitize_dom_id("123start").startswith("id_")
    assert sanitize_dom_id("") == "btn"
    assert len(sanitize_dom_id("x" * 300)) <= 120


def test_build_copy_prompt_html_embeds_json_escaped_text():
    from stock_mining.web.clipboard_button import _json_for_script

    text = 'hello "world"\n<script>alert(1)</script>\n中文🎯'
    html = build_copy_prompt_html(text, element_key="k:1-a")
    # Payload must be script-safe (no raw </script> that can break the HTML parser).
    assert _json_for_script(text) in html
    assert "</script><script>alert" not in html
    assert "\\u003cscript\\u003e" in html
    assert 'id="copy_k_1_a"' in html
    assert "复制 Prompt" in html
    assert "document.execCommand" in html
    assert "navigator.clipboard" in html
    assert "isSecureContext" in html
    assert "setSelectionRange" in html
    assert "min-height: 44px" in html
    assert "touch-action: manipulation" in html
    assert COPY_BUTTON_IFRAME_HEIGHT >= 44


def test_build_copy_prompt_html_handles_empty_and_large_prompt():
    from stock_mining.web.clipboard_button import _json_for_script

    empty = build_copy_prompt_html("", element_key="empty")
    assert "var text = " in empty
    assert _json_for_script("") in empty

    large = "A" * 50_000 + "\n" + "线" * 1_000
    html = build_copy_prompt_html(large, element_key="big")
    assert _json_for_script(large) in html
    # One iframe document should stay bounded for typical review pages.
    assert len(html) < 200_000


def test_build_copy_prompt_html_rejects_broken_button_without_click_handler():
    html = build_copy_prompt_html("x", element_key="btn")
    assert 'addEventListener("click"' in html
    assert "busy" in html  # double-tap guard


def test_copy_prompt_button_calls_st_iframe_once():
    from stock_mining.web import review_app

    recorded: list[dict] = []

    def fake_iframe(body, *, height, width="stretch"):
        recorded.append({"body": body, "height": height, "width": width})

    with patch.object(review_app.st, "iframe", side_effect=fake_iframe):
        review_app._copy_prompt_button("prompt body", element_key="t-key")

    assert len(recorded) == 1
    assert recorded[0]["height"] == COPY_BUTTON_IFRAME_HEIGHT
    assert recorded[0]["width"] == "stretch"
    assert "prompt body" in recorded[0]["body"]
    assert "复制 Prompt" in recorded[0]["body"]


def test_prompt_copy_ui_uses_one_iframe_and_does_not_raise():
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="600519",
        name="贵州茅台",
        market=Market.A,
        track="profitable_growth",
        score=90.0,
        metrics={"price": 100.0},
    )
    service = MagicMock()
    service.strategy_id = "all"

    recorded: list[str] = []

    def fake_iframe(body, **kwargs):
        recorded.append(body)

    with (
        patch.object(review_app.st, "iframe", side_effect=fake_iframe),
        patch.object(review_app.st, "caption"),
        patch.object(review_app.st, "download_button"),
        patch.object(review_app.st, "text_area"),
        patch.object(review_app.st, "expander") as expander,
    ):
        expander.return_value.__enter__ = MagicMock(return_value=None)
        expander.return_value.__exit__ = MagicMock(return_value=False)
        review_app._prompt_copy_ui("hello prompt", service=service, hit=hit, idx=0)

    assert len(recorded) == 1
    assert "hello prompt" in recorded[0]


def _label_map(kind: str) -> str:
    from stock_mining.state.disposition import DispositionKind

    return {
        DispositionKind.NOT_INTERESTED: "不感兴趣",
        DispositionKind.TOO_EXPENSIVE: "价格偏贵",
        DispositionKind.WATCHLIST: "加入自选",
    }[kind]


def test_apply_disposition_change_sets_toast_for_next_paint():
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="301327",
        name="华宝新能",
        market=Market.A,
        track="loss_tolerant_growth",
        score=70.0,
        metrics={"price": 10.0},
    )
    service = MagicMock()
    service.get_disposition_kind.return_value = DispositionKind.TOO_EXPENSIVE
    service.disposition_label.side_effect = _label_map
    state: dict = {}

    with patch.object(review_app.st, "session_state", state):
        changed = review_app.apply_disposition_change(
            service,
            hit,
            DispositionKind.NOT_INTERESTED,
            toast_key="toast-1",
        )

    assert changed is True
    service.set_disposition.assert_called_once_with(hit, DispositionKind.NOT_INTERESTED)
    assert state["toast-1"] == "不感兴趣"


def test_apply_disposition_change_noop_when_unchanged():
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="600519",
        name="贵州茅台",
        market=Market.A,
        track="profitable_growth",
        score=90.0,
        metrics={"price": 100.0},
    )
    service = MagicMock()
    service.get_disposition_kind.return_value = DispositionKind.NOT_INTERESTED
    state: dict = {}

    with patch.object(review_app.st, "session_state", state):
        changed = review_app.apply_disposition_change(
            service,
            hit,
            DispositionKind.NOT_INTERESTED,
            toast_key="toast-1",
        )

    assert changed is False
    service.set_disposition.assert_not_called()
    assert state == {}


def test_disposition_selector_first_paint_uses_primary_after_onclick():
    """iPhone bug: toast on 1st tap but primary color only after 2nd tap."""
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="301327",
        name="华宝新能",
        market=Market.A,
        track="loss_tolerant_growth",
        score=70.0,
        metrics={"price": 10.0},
    )
    service = MagicMock()
    service.strategy_id = "all"
    # Streamlit order: on_click already persisted before this paint.
    service.get_disposition_kind.return_value = DispositionKind.NOT_INTERESTED
    service.disposition_label.side_effect = _label_map

    toast_key = review_app._disposition_toast_key(service, hit, idx=0)
    state = {toast_key: "不感兴趣"}
    button_calls: list[dict] = []
    captions: list[str] = []
    toasts: list[str] = []

    def fake_button(label, *, key="", type="secondary", on_click=None, **kwargs):
        button_calls.append({"label": label, "key": key, "type": type, "on_click": on_click})
        return False

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(review_app.st, "session_state", state),
        patch.object(review_app.st, "caption", side_effect=lambda msg, *a, **k: captions.append(msg)),
        patch.object(review_app.st, "columns", return_value=[col, col, col]),
        patch.object(review_app.st, "button", side_effect=fake_button),
        patch.object(review_app.st, "toast", side_effect=lambda msg, *a, **k: toasts.append(msg)),
        patch.object(review_app.st, "rerun") as rerun,
    ):
        review_app._disposition_selector(service, hit, idx=0)

    rerun.assert_not_called()
    assert any("不感兴趣" in t for t in toasts)
    assert any(c == "当前标记：不感兴趣" for c in captions)
    by_key = {b["key"]: b for b in button_calls}
    ni = next(b for k, b in by_key.items() if "disp-not_interested" in k)
    te = next(b for k, b in by_key.items() if "disp-too_expensive" in k)
    assert ni["type"] == "primary"
    assert te["type"] == "secondary"
    assert ni["on_click"] is review_app.apply_disposition_change
    assert toast_key not in state  # consumed for toast


def test_disposition_selector_wires_onclick_args_for_kind_switch():
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="301327",
        name="华宝新能",
        market=Market.A,
        track="loss_tolerant_growth",
        score=70.0,
        metrics={"price": 10.0},
    )
    service = MagicMock()
    service.strategy_id = "all"
    service.get_disposition_kind.return_value = DispositionKind.TOO_EXPENSIVE
    service.disposition_label.side_effect = _label_map

    wired: dict[str, dict] = {}
    state: dict = {}

    def fake_button(label, *, key="", on_click=None, args=None, kwargs=None, **kw):
        wired[key] = {"on_click": on_click, "args": args, "kwargs": kwargs or {}}
        return False

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(review_app.st, "session_state", state),
        patch.object(review_app.st, "caption"),
        patch.object(review_app.st, "columns", return_value=[col, col, col]),
        patch.object(review_app.st, "button", side_effect=fake_button),
        patch.object(review_app.st, "toast"),
        patch.object(review_app.st, "rerun") as rerun,
    ):
        review_app._disposition_selector(service, hit, idx=0)

        key = next(k for k in wired if "disp-not_interested" in k)
        cb = wired[key]["on_click"]
        args = wired[key]["args"]
        kwargs = wired[key]["kwargs"]
        # Simulate Streamlit invoking on_click before the next paint.
        cb(*args, **kwargs)

    service.set_disposition.assert_called_once_with(hit, DispositionKind.NOT_INTERESTED)
    rerun.assert_not_called()
    toast_key = review_app._disposition_toast_key(service, hit, idx=0)
    assert state[toast_key] == "不感兴趣"


def test_disposition_selector_noop_when_already_selected():
    from stock_mining.state.disposition import DispositionKind
    from stock_mining.web import review_app

    hit = CandidateHit(
        code="600519",
        name="贵州茅台",
        market=Market.A,
        track="profitable_growth",
        score=90.0,
        metrics={"price": 100.0},
    )
    service = MagicMock()
    service.strategy_id = "all"
    service.get_disposition_kind.return_value = DispositionKind.NOT_INTERESTED
    service.disposition_label.side_effect = _label_map

    wired: dict[str, dict] = {}
    state: dict = {}

    def fake_button(label, *, key="", on_click=None, args=None, kwargs=None, **kw):
        wired[key] = {"on_click": on_click, "args": args, "kwargs": kwargs or {}}
        return False

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(review_app.st, "session_state", state),
        patch.object(review_app.st, "caption"),
        patch.object(review_app.st, "columns", return_value=[col, col, col]),
        patch.object(review_app.st, "button", side_effect=fake_button),
        patch.object(review_app.st, "toast") as toast,
        patch.object(review_app.st, "rerun") as rerun,
    ):
        review_app._disposition_selector(service, hit, idx=0)
        key = next(k for k in wired if "disp-not_interested" in k)
        wired[key]["on_click"](*wired[key]["args"], **wired[key]["kwargs"])

    service.set_disposition.assert_not_called()
    toast.assert_not_called()
    rerun.assert_not_called()
    assert state == {}


def test_candidate_card_is_not_streamlit_fragment():
    """Disposition clicks must use a full app run, not a per-card fragment."""
    from stock_mining.web.review_app import _candidate_card

    assert not hasattr(_candidate_card, "fragment_id")
    # ``@st.fragment`` wraps the callable; undecorated function has no __wrapped__.
    assert getattr(_candidate_card, "__wrapped__", None) is None
    assert callable(_candidate_card)


@pytest.mark.parametrize(
    "payload",
    [
        "plain",
        "line1\nline2\r\nline3",
        '{"a":1}',
        "</script><script>alert(1)</script>",
        "🚀" * 100,
    ],
)
def test_build_copy_prompt_html_roundtrip_payload(payload: str):
    html = build_copy_prompt_html(payload, element_key="round")
    # Extract the JS assignment `var text = ...;`
    marker = "var text = "
    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)
    lit = html[start:end]
    assert json.loads(lit) == payload
    assert "</script>" not in lit
    assert "<script>" not in lit
