from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class JiquerError(Exception):
    """Base error for jiquer API calls."""


class JiquerAuthError(JiquerError):
    pass


class JiquerRateLimitError(JiquerError):
    pass


class JiquerAPIError(JiquerError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ChatResponse:
    content: str
    reasoning_content: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class JiquerClientConfig:
    base_url: str = "https://learning-api.jiquer.com/Api/v1/AiAgent"
    model: str = "deepseek"
    api_key: str = ""
    url_style: str = "path"  # path | body
    timeout_sec: float = 180.0
    thinking_extra_body: dict[str, Any] = field(
        default_factory=lambda: {"thinking": {"type": "enabled"}}
    )
    web_search_extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides: Any) -> JiquerClientConfig:
        api_key = overrides.pop("api_key", None) or os.environ.get("JIQUER_API_KEY", "")
        return cls(api_key=api_key, **overrides)


@dataclass
class JiquerClient:
    config: JiquerClientConfig

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        thinking: bool = False,
        web_search: bool = False,
        timeout_sec: float | None = None,
    ) -> ChatResponse:
        if not self.config.api_key:
            raise JiquerAuthError(
                "缺少 API Key。请设置环境变量 JIQUER_API_KEY。"
            )

        body: dict[str, Any] = {"messages": messages}
        if self.config.url_style == "body":
            body["model"] = self.config.model

        if thinking and self.config.thinking_extra_body:
            body.update(_deep_merge({}, self.config.thinking_extra_body))
        if web_search and self.config.web_search_extra_body:
            body.update(_deep_merge({}, self.config.web_search_extra_body))

        url = self._endpoint_url()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )
        timeout = timeout_sec if timeout_sec is not None else self.config.timeout_sec

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in (401, 403):
                raise JiquerAuthError(f"认证失败 ({exc.code}): {detail}") from exc
            if exc.code == 429:
                raise JiquerRateLimitError(f"请求过于频繁 ({exc.code}): {detail}") from exc
            raise JiquerAPIError(
                f"API 错误 ({exc.code}): {detail}",
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise JiquerAPIError(f"网络错误: {exc.reason}") from exc

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise JiquerAPIError(f"响应不是合法 JSON: {raw_text[:200]}") from exc

        return _parse_chat_response(raw)

    def probe(self) -> dict[str, Any]:
        """Minimal request to detect thinking / basic connectivity."""
        response = self.chat(
            [{"role": "user", "content": "回复 OK 两个字母即可。"}],
            thinking=True,
            timeout_sec=min(60.0, self.config.timeout_sec),
        )
        return {
            "ok": True,
            "content": response.content,
            "has_reasoning_content": response.reasoning_content is not None,
            "reasoning_preview": (response.reasoning_content or "")[:200],
            "usage": response.usage,
        }

    def _endpoint_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if self.config.url_style == "path":
            return f"{base}/{self.config.model}/chat/completions"
        return f"{base}/chat/completions"


def _parse_chat_response(raw: dict[str, Any]) -> ChatResponse:
    if "error" in raw:
        message = raw["error"]
        if isinstance(message, dict):
            text = str(message.get("message", message))
        else:
            text = str(message)
        raise JiquerAPIError(text)

    choices = raw.get("choices") or []
    if not choices:
        raise JiquerAPIError(f"响应缺少 choices: {raw}")

    message = choices[0].get("message") or {}
    content = str(message.get("content") or "")
    reasoning = message.get("reasoning_content")
    reasoning_content = str(reasoning) if reasoning else None
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    return ChatResponse(
        content=content,
        reasoning_content=reasoning_content,
        usage=usage,
        raw=raw,
    )


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base
