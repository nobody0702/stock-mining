from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from stock_mining.llm.jiquer_client import (
    JiquerAPIError,
    JiquerAuthError,
    JiquerClient,
    JiquerClientConfig,
)


def _mock_response(payload: dict, *, status: int = 200) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    mock = MagicMock()
    mock.read.return_value = body
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.status = status
    return mock


@patch("stock_mining.llm.jiquer_client.urllib.request.urlopen")
def test_chat_path_url_and_auth_header(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"total_tokens": 10},
        }
    )
    client = JiquerClient(
        JiquerClientConfig(api_key="test-key", url_style="path", model="deepseek")
    )
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "OK"

    request = mock_urlopen.call_args[0][0]
    assert request.full_url.endswith("/deepseek/chat/completions")
    assert request.headers["Authorization"] == "Bearer test-key"


@patch("stock_mining.llm.jiquer_client.urllib.request.urlopen")
def test_chat_body_url_includes_model(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {"choices": [{"message": {"content": "OK"}}]}
    )
    client = JiquerClient(
        JiquerClientConfig(api_key="k", url_style="body", model="deepseek")
    )
    client.chat([{"role": "user", "content": "hi"}])
    request = mock_urlopen.call_args[0][0]
    assert request.full_url.endswith("/chat/completions")
    sent = json.loads(request.data.decode("utf-8"))
    assert sent["model"] == "deepseek"


@patch("stock_mining.llm.jiquer_client.urllib.request.urlopen")
def test_chat_thinking_extra_body(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "answer",
                        "reasoning_content": "think",
                    }
                }
            ]
        }
    )
    client = JiquerClient(
        JiquerClientConfig(
            api_key="k",
            thinking_extra_body={"thinking": {"type": "enabled"}},
        )
    )
    resp = client.chat([{"role": "user", "content": "hi"}], thinking=True)
    sent = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert sent["thinking"] == {"type": "enabled"}
    assert resp.reasoning_content == "think"


@patch("stock_mining.llm.jiquer_client.urllib.request.urlopen")
def test_chat_auth_error(mock_urlopen):
    import urllib.error

    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="http://x",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=BytesIO(b"bad key"),
    )
    client = JiquerClient(JiquerClientConfig(api_key="bad"))
    with pytest.raises(JiquerAuthError):
        client.chat([{"role": "user", "content": "hi"}])


def test_missing_api_key():
    client = JiquerClient(JiquerClientConfig(api_key=""))
    with pytest.raises(JiquerAuthError):
        client.chat([{"role": "user", "content": "hi"}])
