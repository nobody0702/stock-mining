from __future__ import annotations

from stock_mining.config import ScoringConfig
from stock_mining.models import MarketSnapshot, ScreeningContext, StockFinancials
from stock_mining.utils import adaptive_annual_window


def compute_score(ctx: ScreeningContext, config: ScoringConfig) -> tuple[float, dict[str, float]]:
    weights = config.weights
    components: dict[str, float] = {
        "near_low": _score_near_low(ctx.market),
        "drawdown": _score_drawdown(ctx.market),
        "roe": _score_roe(ctx.financials),
        "growth": _score_growth(ctx.financials),
        "cash_quality": _score_cash_quality(ctx.financials),
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
    if financials is not None:
        window = adaptive_annual_window(financials.annual, 3)
        metrics["roe_values"] = [item.roe_pct for item in window]
        if window:
            metrics["latest_net_profit"] = window[-1].net_profit_yuan
            metrics["latest_revenue"] = window[-1].revenue_yuan
    return metrics


def _score_near_low(market: MarketSnapshot | None) -> float:
    if market is None or market.price is None or market.low_52w is None or market.low_52w <= 0:
        return 0.0
    ratio = market.price / market.low_52w
    if ratio <= 1.0:
        return 1.0
    if ratio >= 1.15:
        return 0.0
    return max(0.0, 1.0 - (ratio - 1.0) / 0.15)


def _score_drawdown(market: MarketSnapshot | None) -> float:
    if market is None or market.drawdown_from_high_pct is None:
        return 0.0
    drawdown = market.drawdown_from_high_pct
    if drawdown >= 50:
        return 1.0
    if drawdown <= 10:
        return 0.0
    return (drawdown - 10) / 40.0


def _score_roe(financials: StockFinancials | None) -> float:
    if financials is None:
        return 0.0
    window = adaptive_annual_window(financials.annual, 3)
    values = [item.roe_pct for item in window if item.roe_pct is not None]
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return max(0.0, min(1.0, avg / 20.0))


def _score_growth(financials: StockFinancials | None) -> float:
    if financials is None:
        return 0.0
    window = adaptive_annual_window(financials.annual, 3)
    revenues = [item.revenue_yuan for item in window if item.revenue_yuan is not None]
    if len(revenues) < 2 or revenues[0] <= 0:
        profits = [item.net_profit_yuan for item in window if item.net_profit_yuan is not None]
        if len(profits) < 2 or profits[0] == 0:
            return 0.3
        growth = (profits[-1] - profits[0]) / abs(profits[0])
    else:
        growth = (revenues[-1] - revenues[0]) / revenues[0]
    return max(0.0, min(1.0, 0.5 + growth))


def _score_cash_quality(financials: StockFinancials | None) -> float:
    if financials is None:
        return 0.0
    window = adaptive_annual_window(financials.annual, 1)
    if not window:
        return 0.0
    latest = window[-1]
    if latest.net_profit_yuan is None or latest.net_profit_yuan <= 0:
        return 0.5 if latest.operating_cashflow_per_share and latest.operating_cashflow_per_share > 0 else 0.2
    if latest.operating_cashflow_yuan is None:
        return 0.5 if latest.operating_cashflow_per_share and latest.operating_cashflow_per_share > 0 else 0.0
    ratio = latest.operating_cashflow_yuan / latest.net_profit_yuan
    return max(0.0, min(1.0, ratio))
