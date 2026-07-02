from __future__ import annotations

import os
import random
import time
from typing import Dict, Tuple

import requests
from requests.adapters import HTTPAdapter

_PATCHED = False


def _trust_env_enabled() -> bool:
    value = os.environ.get("STOCK_MINING_TRUST_PROXY", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_akshare_direct_connect() -> None:
    """Bypass broken system/env HTTP proxies for AkShare East Money requests."""
    global _PATCHED
    if _PATCHED or _trust_env_enabled():
        return

    import akshare.utils.request as ak_request

    def request_with_retry(
        url: str,
        params: Dict | None = None,
        timeout: int = 15,
        max_retries: int = 3,
        base_delay: float = 1.0,
        random_delay_range: Tuple[float, float] = (0.5, 1.5),
    ) -> requests.Response:
        last_exception: Exception | None = None

        for attempt in range(max_retries):
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
                    session.mount("http://", adapter)
                    session.mount("https://", adapter)
                    response = session.get(url, params=params, timeout=timeout)
                    response.raise_for_status()
                    return response
            except (requests.RequestException, ValueError) as exc:
                last_exception = exc
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt) + random.uniform(*random_delay_range)
                    time.sleep(delay)

        assert last_exception is not None
        raise last_exception

    ak_request.request_with_retry = request_with_retry

    try:
        import akshare.utils.func as ak_func

        ak_func.request_with_retry = request_with_retry
    except ImportError:
        pass

    _PATCHED = True


def format_proxy_error(exc: BaseException) -> str | None:
    """Return a user-facing hint when a request failed due to proxy settings."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__

    for item in chain:
        name = type(item).__name__
        text = str(item).lower()
        if "proxy" in name.lower() or "proxy" in text:
            return (
                "检测到 HTTP 代理导致请求失败（ProxyError）。"
                "东方财富接口建议直连：请关闭失效的 VPN/代理，"
                "或取消 shell 中的 HTTP_PROXY/HTTPS_PROXY 环境变量。"
                "若你必须走代理访问外网，可设置 STOCK_MINING_TRUST_PROXY=1 恢复默认代理行为。"
            )
    return None
