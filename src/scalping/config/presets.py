"""Preset loading and resolution.

`DASHBOARD_STRATEGY_LAB.md` §1: `effective_config(symbol) = defaults <- class_preset
<- overlays <- per_symbol_override`. Exactly one class preset per symbol; overlays may
only tighten values, never loosen them; frozen strategy parameters are refused at
every layer.

This module is deliberately data-layer-only (no persistence, no API) so P1 can be
tested standalone; the `presets` DB table + versioning + provenance API is Lab phase
L1 and builds on top of this resolver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from scalping.config.frozen import reject_frozen_keys
from scalping.config.settings import EffectiveConfig

#: Fields where a *smaller* value is stricter (tighter). Used to validate that an
#: overlay only tightens a class preset, never loosens it.
_TIGHTEN_DOWN = {
    "strength_max",
    "entry_max_atr",
    "bar_range_max_atr",
    "spread_max_bps",
    "spread_stability_60s_bps",
    "risk_per_trade_pct",
    "risk_per_trade_multiplier",
    "leverage_cap",
    "depth_size_frac",
    "max_positions_in_class",
    "taker_spread_max_bps",
}
#: Fields where a *larger* value is stricter (tighter).
_TIGHTEN_UP = {
    "strength_min",
    "rvol_min",
    "funding_blackout_s",
}


class PresetOverlayViolation(Exception):
    """Raised when an overlay would loosen a gate rather than tighten it."""


class ClassPreset(BaseModel):
    """One resolved class-or-overlay preset entry, pre-merge."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: int = 1
    overlay: bool = False
    disabled: bool = False
    disabled_reason: str | None = None
    values: dict[str, Any] = {}


def _split_known_and_meta(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate strategy-config keys from routing/metadata keys (symbols_match,
    universe_rule, description, etc.) that belong to universe/preset bookkeeping,
    not to `EffectiveConfig`.
    """
    meta_keys = {
        "version",
        "description",
        "symbols_match",
        "universe_rule",
        "overlay",
        "disabled",
        "disabled_reason",
        "observe_only",
        "shorts_bias_note",
        "window_before_min",
        "window_after_min",
        "entries_disabled",
        "funding_rate_abs_max",
        "min_listing_age_days",
        "max_positions_in_class",
        "shorts_enabled",
    }
    known: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for k, v in raw.items():
        (meta if k in meta_keys else known).update({k: v})
    return known, meta


def load_presets_yaml(path: Path) -> dict[str, ClassPreset]:
    raw = yaml.safe_load(path.read_text())
    presets_raw: dict[str, Any] = raw.get("presets", {})
    result: dict[str, ClassPreset] = {}
    for name, body in presets_raw.items():
        known, meta = _split_known_and_meta(body)
        reject_frozen_keys(known.keys(), source=f"preset:{name}")
        result[name] = ClassPreset(
            name=name,
            version=meta.get("version", 1),
            overlay=meta.get("overlay", False),
            disabled=meta.get("disabled", False),
            disabled_reason=meta.get("disabled_reason"),
            values=known,
        )
    return result


_GATE_FIELDS = set(EffectiveConfig.model_fields["gates"].annotation.model_fields)  # type: ignore[union-attr]
_RISK_FIELDS = set(EffectiveConfig.model_fields["risk"].annotation.model_fields)  # type: ignore[union-attr]
_EXIT_FIELDS = set(EffectiveConfig.model_fields["exits"].annotation.model_fields)  # type: ignore[union-attr]
_COST_FIELDS = set(EffectiveConfig.model_fields["cost"].annotation.model_fields)  # type: ignore[union-attr]


def _route(key: str) -> str:
    if key in _GATE_FIELDS:
        return "gates"
    if key in _RISK_FIELDS:
        return "risk"
    if key in _EXIT_FIELDS:
        return "exits"
    if key in _COST_FIELDS:
        return "cost"
    raise KeyError(f"Unknown preset key {key!r} — not present on any EffectiveConfig section")


def _check_tighten_only(
    base: dict[str, Any], overlay: dict[str, Any], *, overlay_name: str
) -> None:
    for key, new_val in overlay.items():
        if key not in base:
            continue  # new key, nothing to compare against
        old_val = base[key]
        if key in _TIGHTEN_DOWN and isinstance(new_val, int | float) and new_val > old_val:
            raise PresetOverlayViolation(
                f"overlay {overlay_name!r} would loosen {key} ({old_val} -> {new_val}); "
                f"overlays may only tighten"
            )
        if key in _TIGHTEN_UP and isinstance(new_val, int | float) and new_val < old_val:
            raise PresetOverlayViolation(
                f"overlay {overlay_name!r} would loosen {key} ({old_val} -> {new_val}); "
                f"overlays may only tighten"
            )


def resolve_effective_config(
    defaults: EffectiveConfig,
    class_preset: ClassPreset | None,
    overlays: list[ClassPreset],
    per_symbol_override: dict[str, Any] | None = None,
) -> EffectiveConfig:
    """Merge `defaults <- class_preset <- overlays <- per_symbol_override`.

    Overlays are validated tighten-only against the *class preset's* resolved value
    (not against defaults) — that is the layer they actually modify.
    """
    merged: dict[str, Any] = {}

    if class_preset is not None:
        reject_frozen_keys(class_preset.values.keys(), source=f"preset:{class_preset.name}")
        merged.update(class_preset.values)

    base_before_overlays = dict(merged)
    for overlay in overlays:
        if not overlay.overlay:
            raise ValueError(f"{overlay.name!r} is not marked overlay:true")
        reject_frozen_keys(overlay.values.keys(), source=f"overlay:{overlay.name}")
        _check_tighten_only(base_before_overlays, overlay.values, overlay_name=overlay.name)
        merged.update(overlay.values)

    if per_symbol_override:
        reject_frozen_keys(per_symbol_override.keys(), source="per_symbol_override")
        merged.update(per_symbol_override)

    sectioned: dict[str, dict[str, Any]] = {"gates": {}, "risk": {}, "exits": {}, "cost": {}}
    for key, value in merged.items():
        try:
            section = _route(key)
        except KeyError:
            continue  # routing/meta key already stripped upstream; ignore defensively
        sectioned[section][key] = value

    out = defaults.model_copy(deep=True)
    out.gates = out.gates.model_copy(update=sectioned["gates"])
    out.risk = out.risk.model_copy(update=sectioned["risk"])
    out.exits = out.exits.model_copy(update=sectioned["exits"])
    out.cost = out.cost.model_copy(update=sectioned["cost"])
    return out
