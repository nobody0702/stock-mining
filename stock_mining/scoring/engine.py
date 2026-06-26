from __future__ import annotations

from stock_mining.config import ScoringConfig
from stock_mining.models import MarketSnapshot, ScreeningContext, StockFinancials
from stock_mining.scoring.valuation import compute_valuation_metrics, load_valuation_scenarios
from stock_mining.utils import adaptive_annual_window

# 子分归一化参考上限（仅用于打分，不影响 filter）
DIVIDEND_YIELD_CAP_PCT = 5.0
PE_CAP = 30.0
PB_CAP = 5.0
PS_CAP = 10.0
LOSS_PB_CAP = 8.0
LOSS_PS_CAP = 12.0
CHEAP_DIVIDEND_WEIGHT = 0.6
CHEAP_VALUATION_WEIGHT = 0.4
LOSS_PB_WEIGHT = 0.7
LOSS_PS_WEIGHT = 0.3


def compute_score(ctx: ScreeningContext, config: ScoringConfig) -> tuple[float, dict[str, float]]:
    weights = config.weights
    components: dict[str, float] = {
        "cheap": _score_cheap(ctx.market, ctx.financials),
        "stability": _score_stability(ctx.financials),
    }
    total_weight = sum(weights.get(key, 0.0) for key in components)
    if total_weight <= 0:
        return 0.0, components
    score = sum(components[key] * weights.get(key, 0.0) for key in components) / total_weight * 100.0
    return score, components


def extract_metrics(ctx: ScreeningContext, score: float, components: dict[str, float]) -> dict[str, object]:
    market = ctx.market
    financials = ctx.financials
    metrics: dict[str, object] = {
        "score": round(score, 2),
        **{f"score_{key}": round(value, 3) for key, value in components.items()},
    }
    latest_revenue: float | None = None
    latest_net_profit: float | None = None
    latest_operating_cashflow: float | None = None
    if financials is not None:
        window = adaptive_annual_window(financials.annual, 3)
        metrics["roe_values"] = [item.roe_pct for item in window]
        if window:
            latest = window[-1]
            latest_net_profit = latest.net_profit_yuan
            latest_revenue = latest.revenue_yuan
            latest_operating_cashflow = latest.operating_cashflow_yuan
            metrics["latest_net_profit"] = latest_net_profit
            metrics["latest_revenue"] = latest_revenue
            metrics["latest_operating_cashflow"] = latest_operating_cashflow
            metrics["profitable"] = _is_profitable(latest_net_profit)
    if market is not None:
        metrics.update(
            {
                "price": market.price,
                "low_52w": market.low_52w,
                "high_52w": market.high_52w,
                "drawdown_pct": market.drawdown_from_high_pct,
                "pe": market.pe,
                "pb": market.pb,
                "ps": market.ps,
                "dividend_yield_pct": market.dividend_yield_pct,
                "industry": market.industry,
            }
        )
        if market.price and market.low_52w and market.low_52w > 0:
            metrics["price_to_low_ratio"] = round(market.price / market.low_52w, 3)
        market_cap = _resolve_market_cap_yuan(
            market,
            latest_revenue_yuan=latest_revenue,
            latest_net_profit_yuan=latest_net_profit,
        )
        if market_cap is not None:
            metrics["market_cap_yuan"] = market_cap
        metrics.update(
            compute_valuation_metrics(
                price=market.price if market is not None else None,
                market_cap_yuan=market_cap,
                latest_net_profit_yuan=latest_net_profit,
                latest_operating_cashflow_yuan=latest_operating_cashflow,
                pe=market.pe if market is not None else None,
                scenarios=load_valuation_scenarios(),
            )
        )
    return metrics


def _resolve_market_cap_yuan(
    market: MarketSnapshot,
    *,
    latest_revenue_yuan: float | None,
    latest_net_profit_yuan: float | None,
) -> float | None:
    if market.market_cap_yuan is not None and market.market_cap_yuan > 0:
        return market.market_cap_yuan
    if (
        market.ps is not None
        and market.ps > 0
        and latest_revenue_yuan is not None
        and latest_revenue_yuan > 0
    ):
        return market.ps * latest_revenue_yuan
    if (
        market.pe is not None
        and market.pe > 0
        and latest_net_profit_yuan is not None
        and latest_net_profit_yuan > 0
    ):
        return market.pe * latest_net_profit_yuan
    return None


def _is_profitable(net_profit_yuan: float | None) -> bool:
    return net_profit_yuan is not None and net_profit_yuan > 0


def _score_cheap(market: MarketSnapshot | None, financials: StockFinancials | None) -> float:
    if market is None:
        return 0.0

    window = adaptive_annual_window(financials.annual, 1) if financials else []
    latest_profit = window[-1].net_profit_yuan if window else None
    profitable = _is_profitable(latest_profit)

    if profitable:
        return _score_cheap_profitable(market)
    return _score_cheap_loss_making(market)


def _score_cheap_profitable(market: MarketSnapshot) -> float:
    dividend_score = _score_high_is_good(
        market.dividend_yield_pct,
        cap=DIVIDEND_YIELD_CAP_PCT,
    )
    valuation_scores = [
        _score_low_is_good(market.pe, cap=PE_CAP),
        _score_low_is_good(market.pb, cap=PB_CAP),
        _score_low_is_good(market.ps, cap=PS_CAP),
    ]
    available = [item for item in valuation_scores if item is not None]

    if dividend_score is None and not available:
        return 0.0
    if dividend_score is None:
        return sum(available) / len(available)
    if not available:
        return dividend_score

    valuation_avg = sum(available) / len(available)
    return CHEAP_DIVIDEND_WEIGHT * dividend_score + CHEAP_VALUATION_WEIGHT * valuation_avg


def _score_cheap_loss_making(market: MarketSnapshot) -> float:
    pb_score = _score_low_is_good(market.pb, cap=LOSS_PB_CAP)
    ps_score = _score_low_is_good(market.ps, cap=LOSS_PS_CAP)

    if pb_score is None and ps_score is None:
        return 0.0
    if pb_score is None:
        return ps_score or 0.0
    if ps_score is None:
        return pb_score

    return LOSS_PB_WEIGHT * pb_score + LOSS_PS_WEIGHT * ps_score


def _score_stability(financials: StockFinancials | None) -> float:
    if financials is None:
        return 0.0

    window = adaptive_annual_window(financials.annual, 5)
    if len(window) < 2:
        window = adaptive_annual_window(financials.annual, 3)
    if len(window) < 2:
        return 0.3

    revenues = [item.revenue_yuan for item in window]
    profits = [item.net_profit_yuan for item in window]

    revenue_score = _series_stability_score(revenues)
    profit_score = _series_stability_score(profits)

    if revenue_score is None and profit_score is None:
        return 0.0
    if revenue_score is None:
        return profit_score or 0.0
    if profit_score is None:
        return revenue_score
    return 0.5 * revenue_score + 0.5 * profit_score


def _series_stability_score(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return None

    first, last = clean[0], clean[-1]
    trend_score = _trend_score(first, last)

    stable_steps = 0
    comparable_steps = 0
    for idx in range(1, len(clean)):
        prior = clean[idx - 1]
        current = clean[idx]
        if prior is None or current is None:
            continue
        if prior == 0:
            if current >= 0:
                stable_steps += 1
            comparable_steps += 1
            continue
        yoy = (current - prior) / abs(prior)
        if yoy >= -0.05:
            stable_steps += 1
        comparable_steps += 1

    step_score = stable_steps / comparable_steps if comparable_steps else 0.5
    return 0.55 * trend_score + 0.45 * step_score


def _trend_score(first: float, last: float) -> float:
    if first > 0:
        change = (last - first) / abs(first)
        if change >= 0.10:
            return min(1.0, 0.75 + change * 0.5)
        if change >= 0:
            return 0.65 + change * 1.0
        if change >= -0.10:
            return 0.55 + (change + 0.10) * 1.0
        return max(0.0, 0.55 + change * 2.5)

    if last > first:
        return 0.55
    if last == first:
        return 0.45
    return max(0.0, 0.35 + (last - first) / max(abs(first), 1.0) * 0.2)


def _score_high_is_good(value: float | None, *, cap: float) -> float | None:
    if value is None or cap <= 0:
        return None
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, value / cap))


def _score_low_is_good(value: float | None, *, cap: float) -> float | None:
    if value is None or cap <= 0:
        return None
    if value <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - value / cap))
