from __future__ import annotations

import re

VALID_TAGS = frozenset({"a", "h", "u"})
_TAGGED_CODE = re.compile(r"^(?P<tag>[ahu]|hk):(?P<code>.+)$", re.IGNORECASE)


def legacy_market_value(raw: str) -> str:
    value = raw.strip().lower()
    if value == "hk":
        return "h"
    return value


def parse_market_tag(value: str) -> str:
    tag = legacy_market_value(value)
    if tag not in VALID_TAGS:
        raise ValueError(f"Unknown market {value!r}; use a, h, u (hk is alias for h)")
    return tag


def normalize_bare_code(tag: str, code: str) -> str:
    market_tag_value = parse_market_tag(tag)
    raw = code.strip().split(".")[0]
    if market_tag_value == "h":
        return raw.zfill(5)
    if market_tag_value == "u":
        return raw.upper()
    return raw.zfill(6)


def normalize_legacy_stock_key(stock_key: str) -> str:
    text = stock_key.strip()
    if text.lower().startswith("hk:"):
        return f"h:{text.split(':', 1)[1]}"
    return text


def parse_tagged_token(token: str, *, default_tag: str = "a") -> tuple[str, str]:
    text = token.strip()
    match = _TAGGED_CODE.match(text)
    if match:
        tag = parse_market_tag(match.group("tag"))
        return tag, normalize_bare_code(tag, match.group("code"))
    tag = parse_market_tag(default_tag)
    return tag, normalize_bare_code(tag, text)
