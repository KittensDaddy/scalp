"""CAEMS v2 A/B validation protocol — strategy-caems.md §Validation protocol.

Each new rule is tested one at a time against the same replay dataset, attributing
expectancy change to a single rule:

| Variant | Change vs v1 |
|---|---|
| A | entry-location condition only |
| B | breakeven move only |
| C | rvol_min 1.3 only |
| D | A+B+C combined |

"Ship the combination only if D >= best single variant on net expectancy with
non-overlapping harm on drawdown." Safety rails (strength cap, candle quality,
funding blackout) ship without A/B but their rejection counts are monitored — any
firing >20% of the time flags its threshold for re-examination.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.backtest.candle_backtester import BacktestResult, run_candle_backtest
from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Candle, Side

#: "v1" baseline: entry-location effectively disabled (very wide), breakeven off,
#: rvol_min at the old (unfiltering) threshold. Variants layer v2 changes on top.
V1_BASELINE_OVERRIDES = {"entry_max_atr": 999.0, "be_enabled": False, "rvol_min": 1.0}

VARIANT_OVERRIDES: dict[str, dict[str, object]] = {
    "A": {"entry_max_atr": 0.5},
    "B": {"be_enabled": True},
    "C": {"rvol_min": 1.3},
    "D": {"entry_max_atr": 0.5, "be_enabled": True, "rvol_min": 1.3},
}

#: Rejection reasons that are safety rails, not edge claims — monitored, not A/B'd.
SAFETY_RAIL_REASONS = ("STRENGTH_TOO_EXTREME", "BAR_RANGE_ABNORMAL", "FUNDING_BLACKOUT")


def _apply_overrides(base: EffectiveConfig, overrides: dict[str, object]) -> EffectiveConfig:
    cfg = base.model_copy(deep=True)
    gate_keys = {"entry_max_atr", "rvol_min"}
    exit_keys = {"be_enabled"}
    gate_updates = {k: v for k, v in overrides.items() if k in gate_keys}
    exit_updates = {k: v for k, v in overrides.items() if k in exit_keys}
    if gate_updates:
        cfg.gates = cfg.gates.model_copy(update=gate_updates)
    if exit_updates:
        cfg.exits = cfg.exits.model_copy(update=exit_updates)
    return cfg


def build_variant_configs(base: EffectiveConfig | None = None) -> dict[str, EffectiveConfig]:
    base = base or EffectiveConfig()
    v1 = _apply_overrides(base, V1_BASELINE_OVERRIDES)
    return {name: _apply_overrides(v1, overrides) for name, overrides in VARIANT_OVERRIDES.items()}


def run_ab_validation(
    candles_1m: list[Candle],
    candles_5m: list[Candle],
    base: EffectiveConfig | None = None,
    frozen: FrozenParams | None = None,
    sides: tuple[Side, ...] = (Side.LONG,),
) -> dict[str, BacktestResult]:
    variants = build_variant_configs(base)
    return {
        name: run_candle_backtest(candles_1m, candles_5m, cfg, frozen, sides)
        for name, cfg in variants.items()
    }


@dataclass(frozen=True)
class ABDecision:
    ship_d: bool
    best_single_variant: str
    detail: str


def decide_ship(results: dict[str, BacktestResult]) -> ABDecision:
    singles = {k: v for k, v in results.items() if k in ("A", "B", "C")}
    best_name = max(singles, key=lambda k: (singles[k].net_expectancy_r or float("-inf")))
    best = singles[best_name]
    d = results["D"]

    d_expectancy = d.net_expectancy_r if d.net_expectancy_r is not None else float("-inf")
    best_expectancy = best.net_expectancy_r if best.net_expectancy_r is not None else float("-inf")
    expectancy_ok = d_expectancy >= best_expectancy
    drawdown_ok = d.max_drawdown_r <= best.max_drawdown_r

    ship = expectancy_ok and drawdown_ok
    detail = (
        f"D net_expectancy={d_expectancy:.4f} vs best({best_name})={best_expectancy:.4f} "
        f"[{'OK' if expectancy_ok else 'WORSE'}]; "
        f"D max_dd={d.max_drawdown_r:.2f}R vs best_dd={best.max_drawdown_r:.2f}R "
        f"[{'OK' if drawdown_ok else 'WORSE'}]"
    )
    return ABDecision(ship_d=ship, best_single_variant=best_name, detail=detail)


def flagged_safety_rails(result: BacktestResult, *, threshold: float = 0.2) -> dict[str, float]:
    """strategy-caems.md: "if any [safety rail] fires >20% of the time, its
    threshold is re-examined." Returns {reason: rate} for any reason over
    `threshold`, keyed against total evaluations (trades + all rejections)."""
    total = result.n + sum(result.rejection_counts.values())
    if total == 0:
        return {}
    flagged = {}
    for reason in SAFETY_RAIL_REASONS:
        count = result.rejection_counts.get(reason, 0)
        rate = count / total
        if rate > threshold:
            flagged[reason] = rate
    return flagged
