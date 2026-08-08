"""Non-short-circuiting CAEMS v2 condition evaluator — SCANNER_DASHBOARD_PLAN.md §S7
("near-trigger detection ... missing-condition list"). `engine.evaluate()` stays a
short-circuiting cascade (the first failing condition determines the rejection
reason, per strategy-caems.md), which is correct for signal decisions but useless for
showing a developing-setup card every condition that still needs to clear. This module
re-checks the same 10 CAEMS-native gates independently, mirroring the "every filter
evaluated, not short-circuited" pattern from `market_data/universe.py`.

Cross-cutting flags (kill switch, stale data, ...) and gates 11/12 (risk, cost — owned
by other modules) are intentionally excluded: a developing setup is about which
*CAEMS* conditions are still missing, not about infrastructure state.
"""

from __future__ import annotations

from dataclasses import dataclass

from scalping.config.frozen import FrozenParams
from scalping.config.settings import EffectiveConfig
from scalping.domain.models import Side
from scalping.strategies.caems.engine import MarketSnapshot


@dataclass(frozen=True)
class ConditionCheck:
    name: str
    passed: bool
    detail: str


def evaluate_conditions(
    *, side: Side, snapshot: MarketSnapshot, config: EffectiveConfig, frozen: FrozenParams
) -> list[ConditionCheck]:
    """Evaluate all 10 CAEMS-native gate conditions independently for one side."""
    s = snapshot
    g = config.gates
    is_long = side is Side.LONG

    strength = (s.ema_fast_1m - s.ema_slow_1m) / s.atr14_1m
    if not is_long:
        strength = -strength

    checks: list[ConditionCheck] = []

    regime_ok = s.ema_fast_5m > s.ema_slow_5m if is_long else s.ema_fast_5m < s.ema_slow_5m
    checks.append(
        ConditionCheck(
            "regime_5m", regime_ok,
            f"5m EMA{'12>48' if is_long else '12<48'} required; fast={s.ema_fast_5m:.4f} "
            f"slow={s.ema_slow_5m:.4f}",
        )
    )

    momentum_ok = s.ema_fast_1m > s.ema_slow_1m if is_long else s.ema_fast_1m < s.ema_slow_1m
    checks.append(
        ConditionCheck(
            "momentum_1m", momentum_ok,
            f"1m EMA{'12>48' if is_long else '12<48'} required; fast={s.ema_fast_1m:.4f} "
            f"slow={s.ema_slow_1m:.4f}",
        )
    )

    deadband_ok = strength >= g.strength_min
    checks.append(
        ConditionCheck(
            "deadband", deadband_ok,
            f"strength {strength:.3f} needs >= {g.strength_min:.3f} "
            f"(gap {g.strength_min - strength:.3f})",
        )
    )

    strength_cap_ok = strength <= g.strength_max
    checks.append(
        ConditionCheck(
            "strength_cap", strength_cap_ok,
            f"strength {strength:.3f} must stay <= {g.strength_max:.3f} "
            f"(over by {strength - g.strength_max:.3f})",
        )
    )

    confirm_ok = s.completed_close > s.ema_fast_1m if is_long else s.completed_close < s.ema_fast_1m
    checks.append(
        ConditionCheck(
            "price_confirmation", confirm_ok,
            f"close {s.completed_close:.4f} vs ema_fast_1m {s.ema_fast_1m:.4f}",
        )
    )

    max_extension = g.entry_max_atr * s.atr14_1m
    extension = (
        s.completed_close - s.ema_fast_1m if is_long else s.ema_fast_1m - s.completed_close
    )
    entry_location_ok = extension <= max_extension
    checks.append(
        ConditionCheck(
            "entry_location", entry_location_ok,
            f"extension {extension:.4f} needs <= {max_extension:.4f} "
            f"(over by {extension - max_extension:.4f})",
        )
    )

    rvol_required = g.rvol_min * s.volume_median_30
    volume_ok = s.completed_quote_volume >= rvol_required
    checks.append(
        ConditionCheck(
            "volume", volume_ok,
            f"quote_volume {s.completed_quote_volume:.2f} needs >= {rvol_required:.2f} "
            f"(rvol_min {g.rvol_min})",
        )
    )

    last_bar_range = s.last_bar_high - s.last_bar_low
    max_bar_range = g.bar_range_max_atr * s.atr14_1m
    candle_quality_ok = last_bar_range <= max_bar_range
    checks.append(
        ConditionCheck(
            "candle_quality", candle_quality_ok,
            f"bar range {last_bar_range:.4f} must stay <= {max_bar_range:.4f}",
        )
    )

    funding_ok = abs(s.seconds_to_next_funding) >= g.funding_blackout_s
    checks.append(
        ConditionCheck(
            "funding_blackout", funding_ok,
            f"seconds_to_funding {s.seconds_to_next_funding:.0f} needs "
            f"|.|>= {g.funding_blackout_s}s",
        )
    )

    spread_ok = s.spread_bps <= g.spread_max_bps
    checks.append(
        ConditionCheck(
            "spread", spread_ok,
            f"spread {s.spread_bps:.3f}bps needs <= {g.spread_max_bps:.3f}bps "
            f"(over by {s.spread_bps - g.spread_max_bps:.3f})",
        )
    )

    return checks
