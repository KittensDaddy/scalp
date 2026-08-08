"""Frozen strategy parameters.

`strategy-caems.md` §Frozen parameters: EMA 12/48, 20/50, ATR 14, TP 1.35R and the
15m time stop are the most overfittable knobs in the system. They stay fixed until
>=300 paper trades produce MAE/MFE distributions; any change is then a **new strategy
version** (caems_v3) validated independently, never a silent edit.

This module makes that a runtime guarantee rather than a comment: the values live on
an immutable model, and every configuration path that could set them (presets, API
edits, per-symbol overrides) routes through :func:`reject_frozen_keys`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenStrategyError(Exception):
    """Raised when a config path attempts to set a frozen strategy parameter."""


class FrozenParams(BaseModel):
    """Immutable. Changing any of these means a new strategy version, not an edit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_version: str = "caems_v2"

    ema_fast_1m: int = 12
    ema_slow_1m: int = 48
    ema_fast_5m: int = 20
    ema_slow_5m: int = 50
    atr_period_1m: int = 14
    volume_median_bars: int = 30

    take_profit_r: float = 1.35
    time_stop_s: int = 15 * 60


#: Every field name that no preset, overlay, per-symbol override, or API edit may set.
FROZEN_KEYS: frozenset[str] = frozenset(FrozenParams.model_fields)


def reject_frozen_keys(keys: object, *, source: str) -> None:
    """Raise :class:`FrozenStrategyError` if ``keys`` contains any frozen parameter.

    ``source`` names the config layer attempting the write, so the error tells the
    operator exactly which preset or request was refused.
    """
    offending = sorted(FROZEN_KEYS.intersection(keys))  # type: ignore[arg-type]
    if offending:
        raise FrozenStrategyError(
            f"{source} attempted to set frozen strategy parameter(s): "
            f"{', '.join(offending)}. These are frozen until >=300 paper trades exist; "
            f"changing them requires a new strategy version (see strategy-caems.md "
            f"§Frozen parameters), not a config edit."
        )
