"""FeatureEngine — turns raw `SymbolState` + context into the normalized
`ScoreInputs` that `scoring.score.score()` weights and sums.

SCANNER_DASHBOARD_PLAN.md §E component sources are descriptive, not a fixed
formula spec ("ROC / candle body ratios, RSI slope", "24h volume percentile + depth
if available"), so the exact mappings here are a documented, tunable starting
point via `FeatureConfig` — analogous to how CAEMS gate thresholds are config, not
frozen. What's load-bearing and non-negotiable is `score.py`'s weighting/summation
and the "no wall-clock reads" purity; the specific feature formulas are expected to
be refined once real scanner data exists.

Two components are intentionally pass-through, not derived here:
`historical_edge` (owned by the calibration store, S10 — zero until that data
exists) and `confirmations` (strategy-specific extras, owned by the strategy
plugin). Both are supplied by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from scalping.domain.models import Side
from scalping.market_data.registry import SymbolState
from scalping.scoring.score import ScoreInputs


@dataclass(frozen=True)
class FeatureConfig:
    rvol_full_credit_at: float = 3.0  # RVOL at/above this -> full relative_volume credit
    atr_pct_target: float = 0.003  # 0.3% ATR/price is the "sweet spot" volatility regime
    atr_pct_band: float = 0.004  # +/- this width around the target still earns credit
    entry_max_atr: float = 0.5  # matches CAEMS gates.entry_max_atr by default
    spread_max_bps: float = 2.0  # matches CAEMS gates.spread_max_bps by default


@dataclass(frozen=True)
class FeatureRawInputs:
    """Everything the feature engine needs beyond `SymbolState` itself. Fields the
    caller already computed elsewhere (cost model, universe ranking, calibration
    store, strategy plugin) are passed straight through rather than recomputed.
    """

    side: Side
    entry_reference: float
    btc_ema_fast_1m: float | None
    btc_ema_slow_1m: float | None
    spread_bps: float
    expected_cost_bps: float
    expected_edge_bps: float
    liquidity_percentile: float  # [0,1], caller-ranked across the universe
    historical_edge_frac: float  # [0,1], from the calibration store; 0 until it exists
    confirmations_frac: float  # [0,1], strategy-specific extras
    stale: bool
    evaluated_at: datetime


def _ema_aligned(fast: float, slow: float, side: Side) -> bool:
    return fast > slow if side is Side.LONG else fast < slow


def compute_features(
    state: SymbolState, raw: FeatureRawInputs, config: FeatureConfig = FeatureConfig()
) -> ScoreInputs:
    is_long = raw.side is Side.LONG

    # -- trend_alignment: 1m + 5m EMA stack agreement, + BTC regime if available.
    # No 15m state is tracked yet (S2 only maintains 1m/5m) -- documented gap, not
    # silently dropped: it contributes a neutral 0.5 rather than being omitted.
    votes = []
    if state.ema_fast_1m.ready and state.ema_slow_1m.ready:
        aligned = _ema_aligned(state.ema_fast_1m.value, state.ema_slow_1m.value, raw.side)
        votes.append(1.0 if aligned else 0.0)
    if state.ema_fast_5m.ready and state.ema_slow_5m.ready:
        aligned = _ema_aligned(state.ema_fast_5m.value, state.ema_slow_5m.value, raw.side)
        votes.append(1.0 if aligned else 0.0)
    votes.append(0.5)  # 15m placeholder
    if raw.btc_ema_fast_1m is not None and raw.btc_ema_slow_1m is not None:
        aligned = _ema_aligned(raw.btc_ema_fast_1m, raw.btc_ema_slow_1m, raw.side)
        votes.append(1.0 if aligned else 0.0)
    else:
        votes.append(0.5)
    trend_alignment_frac = sum(votes) / len(votes)

    # -- momentum: reuses CAEMS strength (EMA gap / ATR) as the momentum proxy
    # until a dedicated ROC/RSI feature pipeline exists.
    momentum_frac = 0.0
    momentum_ready = (
        state.ema_fast_1m.ready and state.ema_slow_1m.ready
        and state.atr_1m.ready and state.atr_1m.value
    )
    if momentum_ready:
        strength = (state.ema_fast_1m.value - state.ema_slow_1m.value) / state.atr_1m.value
        if not is_long:
            strength = -strength
        momentum_frac = max(0.0, min(1.0, strength))

    # -- relative_volume: last closed bar's quote volume vs the prior-30 median.
    rvol_frac = 0.0
    if state.last_candle_1m is not None:
        median = state.volume_median_30.median()
        if median and median > 0:
            rvol = state.last_candle_1m.quote_volume / median
            denom = max(config.rvol_full_credit_at - 1.0, 1e-9)
            rvol_frac = max(0.0, min(1.0, (rvol - 1.0) / denom))

    # -- entry_quality: how close to the EMA the entry reference is, in ATR units
    # (closer = better; matches CAEMS's own "don't chase" entry-location logic).
    entry_quality_frac = 0.0
    if state.ema_fast_1m.ready and state.atr_1m.ready and state.atr_1m.value:
        distance_atr = abs(raw.entry_reference - state.ema_fast_1m.value) / state.atr_1m.value
        entry_quality_frac = max(0.0, 1.0 - distance_atr / config.entry_max_atr)

    # -- volatility_regime: ATR% within a tradable band; too low or too high -> 0.
    volatility_regime_frac = 0.0
    if state.atr_1m.ready and raw.entry_reference > 0:
        atr_pct = state.atr_1m.value / raw.entry_reference
        distance = abs(atr_pct - config.atr_pct_target)
        volatility_regime_frac = max(0.0, 1.0 - distance / config.atr_pct_band)

    # -- spread_penalty / slippage_penalty: severity in [0,1].
    spread_penalty_frac = max(0.0, min(1.0, raw.spread_bps / config.spread_max_bps))
    slippage_penalty_frac = (
        1.0 if raw.expected_edge_bps <= 0
        else max(0.0, min(1.0, raw.expected_cost_bps / raw.expected_edge_bps))
    )

    return ScoreInputs(
        trend_alignment_frac=trend_alignment_frac,
        momentum_frac=momentum_frac,
        relative_volume_frac=rvol_frac,
        entry_quality_frac=entry_quality_frac,
        historical_edge_frac=raw.historical_edge_frac,
        liquidity_frac=max(0.0, min(1.0, raw.liquidity_percentile)),
        volatility_regime_frac=volatility_regime_frac,
        confirmations_frac=max(0.0, min(1.0, raw.confirmations_frac)),
        spread_penalty_frac=spread_penalty_frac,
        slippage_penalty_frac=slippage_penalty_frac,
        stale=raw.stale,
        evaluated_at=raw.evaluated_at,
    )
