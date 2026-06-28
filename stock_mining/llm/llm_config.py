from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from stock_mining.llm.jiquer_client import JiquerClient, JiquerClientConfig
from stock_mining.llm.web_context import WebContextConfig


@dataclass
class JiquerYamlConfig:
    base_url: str = "https://learning-api.jiquer.com/Api/v1/AiAgent"
    model: str = "deepseek"
    url_style: str = "path"
    timeout_sec: float = 180.0
    thinking_enabled_by_default: bool = False
    thinking_extra_body: dict[str, Any] = field(
        default_factory=lambda: {"thinking": {"type": "enabled"}}
    )
    web_search_enabled_by_default: bool = False
    web_search_extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class LlmYamlConfig:
    jiquer: JiquerYamlConfig = field(default_factory=JiquerYamlConfig)
    web_context: WebContextConfig = field(default_factory=WebContextConfig)


def load_llm_config(path: str | Path) -> LlmYamlConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    jiquer = raw.get("jiquer", {})
    thinking = jiquer.get("thinking", {}) or {}
    web_search = jiquer.get("web_search", {}) or {}
    wc_raw = raw.get("web_context", {}) or {}
    queries = wc_raw.get("search_queries")
    if isinstance(queries, list):
        search_queries = tuple(str(q) for q in queries)
    else:
        search_queries = WebContextConfig().search_queries
    return LlmYamlConfig(
        jiquer=JiquerYamlConfig(
            base_url=str(jiquer.get("base_url", JiquerYamlConfig.base_url)),
            model=str(jiquer.get("model", "deepseek")),
            url_style=str(jiquer.get("url_style", "path")),
            timeout_sec=float(jiquer.get("timeout_sec", 180)),
            thinking_enabled_by_default=bool(thinking.get("enabled_by_default", False)),
            thinking_extra_body=dict(
                thinking.get("extra_body") or {"thinking": {"type": "enabled"}}
            ),
            web_search_enabled_by_default=bool(web_search.get("enabled_by_default", False)),
            web_search_extra_body=dict(web_search.get("extra_body") or {}),
        ),
        web_context=WebContextConfig(
            enabled_by_default=bool(wc_raw.get("enabled_by_default", False)),
            notice_days=int(wc_raw.get("notice_days", 365)),
            max_notices=int(wc_raw.get("max_notices", 20)),
            max_dividend_records=int(wc_raw.get("max_dividend_records", 8)),
            max_repurchase_records=int(wc_raw.get("max_repurchase_records", 5)),
            search_queries=search_queries,
            max_search_results_per_query=int(wc_raw.get("max_search_results_per_query", 3)),
            enable_notices=bool(wc_raw.get("enable_notices", True)),
            enable_notice_classification=bool(
                wc_raw.get("enable_notice_classification", True)
            ),
            enable_dividends=bool(wc_raw.get("enable_dividends", True)),
            enable_repurchase=bool(wc_raw.get("enable_repurchase", True)),
            enable_pledge=bool(wc_raw.get("enable_pledge", True)),
            enable_web_search=bool(wc_raw.get("enable_web_search", True)),
            jiquer_native_search=bool(wc_raw.get("jiquer_native_search", False)),
        ),
    )


def build_jiquer_client(
    yaml_config: LlmYamlConfig | JiquerYamlConfig,
    *,
    api_key: str | None = None,
) -> JiquerClient:
    jiquer = yaml_config.jiquer if isinstance(yaml_config, LlmYamlConfig) else yaml_config
    cfg = JiquerClientConfig.from_env(
        base_url=jiquer.base_url,
        model=jiquer.model,
        url_style=jiquer.url_style,
        timeout_sec=jiquer.timeout_sec,
        thinking_extra_body=jiquer.thinking_extra_body,
        web_search_extra_body=jiquer.web_search_extra_body,
        api_key=api_key or "",
    )
    return JiquerClient(cfg)
