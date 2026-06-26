from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ValuationConfig:
    """Simple margin-of-safety assumptions for PE and Gordon-growth DCF."""

    discount_rate: float = 0.10
    terminal_growth: float = 0.03
    fair_pe: float = 15.0


@dataclass(frozen=True)
class ValuationTier:
    id: str
    label: str
    fair_pe: float
    discount_rate: float
    terminal_growth: float
    typical_for: str = ""

    def as_config(self) -> ValuationConfig:
        return ValuationConfig(
            discount_rate=self.discount_rate,
            terminal_growth=self.terminal_growth,
            fair_pe=self.fair_pe,
        )


@dataclass(frozen=True)
class ValuationScenarioConfig:
    default_tier_id: str
    tiers: tuple[ValuationTier, ...]

    def default_tier(self) -> ValuationTier:
        for tier in self.tiers:
            if tier.id == self.default_tier_id:
                return tier
        return self.tiers[0]

    def as_default_config(self) -> ValuationConfig:
        return self.default_tier().as_config()


DEFAULT_TIERS: tuple[ValuationTier, ...] = (
    ValuationTier(
        id="deep_value",
        label="深度价值",
        fair_pe=10.0,
        discount_rate=0.12,
        terminal_growth=0.02,
        typical_for="周期股、低增长成熟股、强调硬折扣的安全边际",
    ),
    ValuationTier(
        id="baseline",
        label="基准白马",
        fair_pe=15.0,
        discount_rate=0.10,
        terminal_growth=0.03,
        typical_for="一般优质企业、市场中枢假设",
    ),
    ValuationTier(
        id="quality_compounder",
        label="品质复利",
        fair_pe=20.0,
        discount_rate=0.09,
        terminal_growth=0.04,
        typical_for="护城河强、ROE 高、可长期复利的消费/制造龙头",
    ),
    ValuationTier(
        id="elite_franchise",
        label="顶级特许",
        fair_pe=25.0,
        discount_rate=0.08,
        terminal_growth=0.04,
        typical_for="稀缺品牌、极强定价权、机构十年视角的极少数标的",
    ),
)

DEFAULT_SCENARIO = ValuationScenarioConfig(default_tier_id="baseline", tiers=DEFAULT_TIERS)
DEFAULT_VALUATION = DEFAULT_SCENARIO.as_default_config()


def load_valuation_scenarios(path: str | Path | None = None) -> ValuationScenarioConfig:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "analysis_dimensions.yaml"
    config_path = Path(path)
    if not config_path.is_file():
        return DEFAULT_SCENARIO

    with config_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    block = raw.get("valuation") or {}

    tiers_raw = block.get("tiers")
    if not tiers_raw:
        return ValuationScenarioConfig(
            default_tier_id=str(block.get("default_tier", "baseline")),
            tiers=(
                ValuationTier(
                    id="baseline",
                    label="基准白马",
                    fair_pe=float(block.get("fair_pe", DEFAULT_VALUATION.fair_pe)),
                    discount_rate=float(
                        block.get("discount_rate", DEFAULT_VALUATION.discount_rate)
                    ),
                    terminal_growth=float(
                        block.get("terminal_growth", DEFAULT_VALUATION.terminal_growth)
                    ),
                    typical_for=str(block.get("typical_for", DEFAULT_TIERS[1].typical_for)),
                ),
            ),
        )

    tiers: list[ValuationTier] = []
    for item in tiers_raw:
        tiers.append(
            ValuationTier(
                id=str(item["id"]),
                label=str(item.get("label", item["id"])),
                fair_pe=float(item["fair_pe"]),
                discount_rate=float(item["discount_rate"]),
                terminal_growth=float(item["terminal_growth"]),
                typical_for=str(item.get("typical_for", "")),
            )
        )
    default_tier_id = str(block.get("default_tier", tiers[0].id if tiers else "baseline"))
    return ValuationScenarioConfig(default_tier_id=default_tier_id, tiers=tuple(tiers))


def load_valuation_config(path: str | Path | None = None) -> ValuationConfig:
    return load_valuation_scenarios(path).as_default_config()


def compute_valuation_metrics(
    *,
    price: float | None,
    market_cap_yuan: float | None,
    latest_net_profit_yuan: float | None,
    latest_operating_cashflow_yuan: float | None,
    pe: float | None,
    config: ValuationConfig | None = None,
    scenarios: ValuationScenarioConfig | None = None,
) -> dict[str, Any]:
    if scenarios is not None:
        scenario_cfg = scenarios
    elif config is not None:
        scenario_cfg = ValuationScenarioConfig(
            default_tier_id="custom",
            tiers=(
                ValuationTier(
                    id="custom",
                    label="自定义",
                    fair_pe=config.fair_pe,
                    discount_rate=config.discount_rate,
                    terminal_growth=config.terminal_growth,
                ),
            ),
        )
    else:
        scenario_cfg = load_valuation_scenarios()

    default_tier = scenario_cfg.default_tier()
    cfg = config or default_tier.as_config()

    metrics: dict[str, Any] = {
        "valuation_default_tier": default_tier.id,
        "valuation_discount_rate": cfg.discount_rate,
        "valuation_terminal_growth": cfg.terminal_growth,
        "valuation_fair_pe": cfg.fair_pe,
    }

    owner_earnings = _pick_owner_earnings(
        latest_operating_cashflow_yuan,
        latest_net_profit_yuan,
    )
    if owner_earnings is not None:
        metrics["owner_earnings_yuan"] = owner_earnings
        if latest_operating_cashflow_yuan is not None and latest_operating_cashflow_yuan > 0:
            metrics["owner_earnings_source"] = "operating_cashflow"
        else:
            metrics["owner_earnings_source"] = "net_profit"

    tier_rows: list[dict[str, Any]] = []
    for tier in scenario_cfg.tiers:
        tier_metrics = _compute_tier_metrics(
            price=price,
            market_cap_yuan=market_cap_yuan,
            latest_net_profit_yuan=latest_net_profit_yuan,
            owner_earnings=owner_earnings,
            pe=pe,
            config=tier.as_config(),
        )
        tier_rows.append(
            {
                "id": tier.id,
                "label": tier.label,
                "fair_pe": tier.fair_pe,
                "discount_rate": tier.discount_rate,
                "terminal_growth": tier.terminal_growth,
                "typical_for": tier.typical_for,
                **tier_metrics,
            }
        )

    metrics["valuation_tiers"] = tier_rows

    default_row = next(row for row in tier_rows if row["id"] == default_tier.id)
    metrics.update(_default_tier_flat_metrics(default_row))

    return metrics


def _default_tier_flat_metrics(row: dict[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = {
        "valuation_pe_available": row.get("pe_available", False),
        "valuation_dcf_available": row.get("dcf_available", False),
    }
    for key in (
        "intrinsic_value_pe_yuan",
        "intrinsic_price_pe",
        "margin_of_safety_pe_pct",
        "intrinsic_value_dcf_yuan",
        "intrinsic_price_dcf",
        "margin_of_safety_dcf_pct",
        "dcf_next_year_cash_yuan",
    ):
        if key in row and row[key] is not None:
            block[key] = row[key]

    mos_values = [
        value
        for key, value in block.items()
        if key.startswith("margin_of_safety_") and key.endswith("_pct") and value is not None
    ]
    if mos_values:
        block["margin_of_safety_pct"] = round(min(mos_values), 2)
    return block


def _compute_tier_metrics(
    *,
    price: float | None,
    market_cap_yuan: float | None,
    latest_net_profit_yuan: float | None,
    owner_earnings: float | None,
    pe: float | None,
    config: ValuationConfig,
) -> dict[str, Any]:
    block: dict[str, Any] = {}
    pe_block = _compute_pe_margin(
        price=price,
        market_cap_yuan=market_cap_yuan,
        latest_net_profit_yuan=latest_net_profit_yuan,
        pe=pe,
        config=config,
    )
    dcf_block = _compute_dcf_margin(
        price=price,
        market_cap_yuan=market_cap_yuan,
        owner_earnings=owner_earnings,
        config=config,
    )

    block["pe_available"] = pe_block.get("valuation_pe_available", False)
    block["dcf_available"] = dcf_block.get("valuation_dcf_available", False)
    mapping = {
        "intrinsic_value_pe_yuan": "intrinsic_value_pe_yuan",
        "intrinsic_price_pe": "intrinsic_price_pe",
        "margin_of_safety_pe_pct": "margin_of_safety_pe_pct",
        "intrinsic_value_dcf_yuan": "intrinsic_value_dcf_yuan",
        "intrinsic_price_dcf": "intrinsic_price_dcf",
        "margin_of_safety_dcf_pct": "margin_of_safety_dcf_pct",
        "dcf_next_year_cash_yuan": "dcf_next_year_cash_yuan",
    }
    for target_key, source_key in mapping.items():
        if source_key in pe_block:
            block[target_key] = pe_block[source_key]
        elif source_key in dcf_block:
            block[target_key] = dcf_block[source_key]

    mos_values = [
        value
        for key, value in block.items()
        if key.startswith("margin_of_safety_") and key.endswith("_pct") and value is not None
    ]
    if mos_values:
        block["margin_of_safety_pct"] = round(min(mos_values), 2)
    return block


def _pick_owner_earnings(
    operating_cashflow_yuan: float | None,
    net_profit_yuan: float | None,
) -> float | None:
    if operating_cashflow_yuan is not None and operating_cashflow_yuan > 0:
        return operating_cashflow_yuan
    if net_profit_yuan is not None and net_profit_yuan > 0:
        return net_profit_yuan
    return None


def _compute_pe_margin(
    *,
    price: float | None,
    market_cap_yuan: float | None,
    latest_net_profit_yuan: float | None,
    pe: float | None,
    config: ValuationConfig,
) -> dict[str, Any]:
    if latest_net_profit_yuan is None or latest_net_profit_yuan <= 0:
        return {"valuation_pe_available": False}

    intrinsic_market_cap = latest_net_profit_yuan * config.fair_pe
    block: dict[str, Any] = {
        "valuation_pe_available": True,
        "intrinsic_value_pe_yuan": round(intrinsic_market_cap, 2),
    }

    if pe is not None and pe > 0:
        block["margin_of_safety_pe_pct"] = round((1.0 - pe / config.fair_pe) * 100.0, 2)
        if price is not None and price > 0:
            block["intrinsic_price_pe"] = round(price * config.fair_pe / pe, 3)

    if market_cap_yuan is not None and market_cap_yuan > 0 and intrinsic_market_cap > 0:
        block["margin_of_safety_pe_pct"] = round(
            (intrinsic_market_cap - market_cap_yuan) / intrinsic_market_cap * 100.0,
            2,
        )
        if price is not None and price > 0:
            block["intrinsic_price_pe"] = round(
                price * intrinsic_market_cap / market_cap_yuan,
                3,
            )

    return block


def _compute_dcf_margin(
    *,
    price: float | None,
    market_cap_yuan: float | None,
    owner_earnings: float | None,
    config: ValuationConfig,
) -> dict[str, Any]:
    spread = config.discount_rate - config.terminal_growth
    if owner_earnings is None or owner_earnings <= 0 or spread <= 0:
        return {"valuation_dcf_available": False}

    next_year_cash = owner_earnings * (1.0 + config.terminal_growth)
    intrinsic_market_cap = next_year_cash / spread
    block: dict[str, Any] = {
        "valuation_dcf_available": True,
        "intrinsic_value_dcf_yuan": round(intrinsic_market_cap, 2),
        "dcf_next_year_cash_yuan": round(next_year_cash, 2),
    }

    if market_cap_yuan is not None and market_cap_yuan > 0 and intrinsic_market_cap > 0:
        block["margin_of_safety_dcf_pct"] = round(
            (intrinsic_market_cap - market_cap_yuan) / intrinsic_market_cap * 100.0,
            2,
        )
        if price is not None and price > 0:
            block["intrinsic_price_dcf"] = round(
                price * intrinsic_market_cap / market_cap_yuan,
                3,
            )

    return block
