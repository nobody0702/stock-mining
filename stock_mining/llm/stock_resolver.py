from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.models import StockInfo


class StockResolveError(Exception):
    pass


@dataclass(frozen=True)
class ResolvedStock:
    code: str
    name: str
    market: Market


def resolve_stock_inputs(
    inputs: list[str],
    *,
    market: Market,
    list_stocks_fn,
) -> list[ResolvedStock]:
    if not inputs:
        raise StockResolveError("未提供股票代码或名称")

    catalog = list_stocks_fn()
    by_code: dict[str, StockInfo] = {item.code: item for item in catalog}
    by_name_exact: dict[str, list[StockInfo]] = {}
    for item in catalog:
        by_name_exact.setdefault(item.name, []).append(item)

    resolved: list[ResolvedStock] = []
    for raw in _expand_inputs(inputs):
        token = raw.strip()
        if not token:
            continue
        resolved.append(_resolve_one(token, market=market, by_code=by_code, by_name_exact=by_name_exact))
    if not resolved:
        raise StockResolveError("未解析到有效股票")
    return resolved


def _expand_inputs(inputs: list[str]) -> list[str]:
    expanded: list[str] = []
    for item in inputs:
        if item.startswith("@"):
            path = Path(item[1:])
            if not path.is_file():
                raise StockResolveError(f"文件不存在: {path}")
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    expanded.append(line)
        elif "," in item:
            expanded.extend(part.strip() for part in item.split(",") if part.strip())
        else:
            expanded.append(item)
    return expanded


def _resolve_one(
    token: str,
    *,
    market: Market,
    by_code: dict[str, StockInfo],
    by_name_exact: dict[str, list[StockInfo]],
) -> ResolvedStock:
    if _looks_like_code(token):
        code = normalize_stock_code(token, market)
        hit = by_code.get(code)
        if hit is None:
            raise StockResolveError(f"未找到股票代码: {market.value}:{code}")
        return ResolvedStock(code=hit.code, name=hit.name, market=hit.market)

    exact = by_name_exact.get(token)
    if exact:
        if len(exact) > 1:
            options = ", ".join(f"{item.market.value}:{item.code} {item.name}" for item in exact)
            raise StockResolveError(f"名称「{token}」对应多只股票: {options}")
        item = exact[0]
        return ResolvedStock(code=item.code, name=item.name, market=item.market)

    fuzzy = [item for item in by_code.values() if token in item.name]
    if len(fuzzy) == 1:
        item = fuzzy[0]
        return ResolvedStock(code=item.code, name=item.name, market=item.market)
    if len(fuzzy) > 1:
        options = ", ".join(f"{item.market.value}:{item.code} {item.name}" for item in fuzzy[:8])
        raise StockResolveError(f"名称「{token}」模糊匹配到多只: {options}")

    raise StockResolveError(f"未找到股票: {token}")


def _looks_like_code(token: str) -> bool:
    stripped = token.strip().lower()
    if stripped.startswith(("sh", "sz", "bj")):
        stripped = stripped[2:]
    return stripped.isdigit() and len(stripped) in (5, 6)
