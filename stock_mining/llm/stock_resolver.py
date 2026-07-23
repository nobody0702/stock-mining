from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stock_mining.markets.base import Market, normalize_stock_code
from stock_mining.models import StockInfo

_MARKET_LABEL = {
    Market.A: "A股",
    Market.HK: "港股",
    Market.US: "美股",
}


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
    allow_unknown_code: bool = False,
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
        resolved.append(
            _resolve_one(
                token,
                market=market,
                by_code=by_code,
                by_name_exact=by_name_exact,
                allow_unknown_code=allow_unknown_code,
            )
        )
    if not resolved:
        raise StockResolveError("未解析到有效股票：输入为空或仅含空白/注释行")
    return resolved


def _expand_inputs(inputs: list[str]) -> list[str]:
    expanded: list[str] = []
    for item in inputs:
        if item.startswith("@"):
            path = Path(item[1:])
            if not path.is_file():
                raise StockResolveError(f"股票列表文件不存在: {path}")
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
    allow_unknown_code: bool = False,
) -> ResolvedStock:
    if _looks_like_code(token):
        code = normalize_stock_code(token, market)
        hit = by_code.get(code)
        if hit is None:
            if allow_unknown_code:
                return ResolvedStock(code=code, name=code, market=market)
            raise StockResolveError(_code_not_found_message(market, code))
        return ResolvedStock(code=hit.code, name=hit.name, market=hit.market)

    exact = by_name_exact.get(token)
    if exact:
        if len(exact) > 1:
            options = ", ".join(f"{item.market.value}:{item.code} {item.name}" for item in exact)
            raise StockResolveError(
                f"名称「{token}」对应多只股票（{options}）。请改用带市场前缀的代码，"
                f"例如 a:600519 或 h:00700。"
            )
        item = exact[0]
        return ResolvedStock(code=item.code, name=item.name, market=item.market)

    fuzzy = [item for item in by_code.values() if token in item.name]
    if len(fuzzy) == 1:
        item = fuzzy[0]
        return ResolvedStock(code=item.code, name=item.name, market=item.market)
    if len(fuzzy) > 1:
        options = ", ".join(f"{item.market.value}:{item.code} {item.name}" for item in fuzzy[:8])
        raise StockResolveError(
            f"名称「{token}」模糊匹配到多只股票（{options}）。请输入更完整的名称，或直接用股票代码。"
        )

    raise StockResolveError(_name_not_found_message(market, token))


def _code_not_found_message(market: Market, code: str) -> str:
    label = _MARKET_LABEL.get(market, market.value)
    key = f"{market.value}:{code}"
    if market == Market.HK:
        return (
            f"在{label}行情目录中未找到代码 {key}。"
            f"请确认：市场已选「港股」、代码为 5 位（如 00700 / 01045）、该股仍在上市。"
            f"说明：每日筛股仅覆盖港股通，但单股查询支持全部港股；若目录中也没有，通常是代码有误或已退市。"
        )
    return (
        f"在{label}股票列表中未找到代码 {key}。"
        f"请确认代码正确，或改用股票名称；并确认未误选「港股」市场。"
    )


def _name_not_found_message(market: Market, token: str) -> str:
    label = _MARKET_LABEL.get(market, market.value)
    return (
        f"在{label}名单中未找到名称「{token}」。"
        f"可改用股票代码查询，或检查是否选错市场（A股 / 港股）。"
    )


def _looks_like_code(token: str) -> bool:
    stripped = token.strip().lower()
    if stripped.startswith(("sh", "sz", "bj")):
        stripped = stripped[2:]
    return stripped.isdigit() and len(stripped) in (5, 6)
