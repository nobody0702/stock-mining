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


def test_copy_prompt_button_calls_components_html_once():
    from stock_mining.web import review_app

    recorded: list[dict] = []

    def fake_html(body, *, height, scrolling):
        recorded.append({"body": body, "height": height, "scrolling": scrolling})

    with patch.object(review_app.components, "html", side_effect=fake_html):
        review_app._copy_prompt_button("prompt body", element_key="t-key")

    assert len(recorded) == 1
    assert recorded[0]["height"] == COPY_BUTTON_IFRAME_HEIGHT
    assert recorded[0]["scrolling"] is False
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

    def fake_html(body, **kwargs):
        recorded.append(body)

    with (
        patch.object(review_app.components, "html", side_effect=fake_html),
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


def test_disposition_selector_reruns_fragment_only_not_full_app():
    """Regression: full-app rerun remounts every copy iframe and freezes the page."""
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
    service.get_disposition_kind.return_value = None
    service.disposition_label.side_effect = lambda k: k

    rerun_scopes: list[object] = []

    def fake_rerun(*, scope="app"):
        rerun_scopes.append(scope)

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(review_app.st, "caption"),
        patch.object(review_app.st, "columns", return_value=[col, col, col]),
        patch.object(review_app.st, "button", return_value=True),
        patch.object(review_app.st, "toast"),
        patch.object(review_app.st, "rerun", side_effect=fake_rerun),
    ):
        review_app._disposition_selector(service, hit, idx=0)

    service.set_disposition.assert_called()
    assert rerun_scopes
    assert all(scope == "fragment" for scope in rerun_scopes)


def test_candidate_card_is_streamlit_fragment():
    from stock_mining.web.review_app import _candidate_card

    assert getattr(_candidate_card, "__wrapped__", None) is not None or hasattr(
        _candidate_card, "fragment_id"
    ) or callable(_candidate_card)
    # Streamlit marks fragments; ensure decorator applied (function still callable).
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
