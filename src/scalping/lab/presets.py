"""Strategy Lab preset persistence + resolution with provenance — L1.

Builds on `config/presets.py`'s merge rules. Editing a preset always inserts a
new version row (append-only). Live activation is gated separately (L6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scalping.config.frozen import reject_frozen_keys
from scalping.config.presets import (
    ClassPreset,
    PresetOverlayViolation,
    _check_tighten_only,
    _route,
    resolve_effective_config,
)
from scalping.config.settings import EffectiveConfig


@dataclass(frozen=True)
class PresetRecord:
    preset_id: str
    name: str
    version: int
    class_rule: dict[str, Any]
    params: dict[str, Any]
    overlay: bool
    disabled: bool
    created_at: datetime
    author: str
    note: str
    activated_paper: bool = False
    activated_live: bool = False


@dataclass(frozen=True)
class ProvenanceEntry:
    key: str
    value: Any
    layer: str  # defaults | class_preset | overlay | per_symbol


@dataclass(frozen=True)
class ResolvedConfigView:
    config: EffectiveConfig
    provenance: list[ProvenanceEntry]


def resolve_with_provenance(
    defaults: EffectiveConfig,
    class_preset: ClassPreset | None,
    overlays: list[ClassPreset],
    per_symbol_override: dict[str, Any] | None = None,
) -> ResolvedConfigView:
    """Same merge as `resolve_effective_config`, plus per-key provenance."""
    provenance: dict[str, ProvenanceEntry] = {}

    def _mark(layer: str, values: dict[str, Any]) -> None:
        for k, v in values.items():
            provenance[k] = ProvenanceEntry(key=k, value=v, layer=layer)

    # defaults first (all gate/risk/exit/cost fields)
    for section_name in ("gates", "risk", "exits", "cost"):
        section = getattr(defaults, section_name)
        for k, v in section.model_dump().items():
            provenance[k] = ProvenanceEntry(key=k, value=v, layer="defaults")

    if class_preset is not None:
        reject_frozen_keys(class_preset.values.keys(), source=f"preset:{class_preset.name}")
        _mark("class_preset", class_preset.values)

    base_before_overlays = dict(class_preset.values) if class_preset else {}
    for overlay in overlays:
        if not overlay.overlay:
            raise ValueError(f"{overlay.name!r} is not marked overlay:true")
        reject_frozen_keys(overlay.values.keys(), source=f"overlay:{overlay.name}")
        _check_tighten_only(base_before_overlays, overlay.values, overlay_name=overlay.name)
        _mark("overlay", overlay.values)

    if per_symbol_override:
        reject_frozen_keys(per_symbol_override.keys(), source="per_symbol_override")
        _mark("per_symbol", per_symbol_override)

    config = resolve_effective_config(
        defaults, class_preset, overlays, per_symbol_override
    )
    return ResolvedConfigView(
        config=config,
        provenance=sorted(provenance.values(), key=lambda p: p.key),
    )


def validate_new_version_params(
    params: dict[str, Any],
    *,
    overlay: bool,
    base_params: dict[str, Any] | None = None,
    name: str = "draft",
) -> None:
    """Refuse frozen keys; enforce tighten-only when saving an overlay version."""
    reject_frozen_keys(params.keys(), source=f"preset:{name}")
    # unknown keys that can't route into EffectiveConfig are rejected
    for key in params:
        try:
            _route(key)
        except KeyError as exc:
            raise KeyError(str(exc)) from exc
    if overlay and base_params is not None:
        _check_tighten_only(base_params, params, overlay_name=name)


@dataclass
class LiveActivationGate:
    """L6 server-side gates for LIVE preset activation."""

    min_paper_trades: int = 50
    require_completed_backtest: bool = True


def can_activate_live(
    *,
    has_completed_backtest: bool,
    paper_trade_count: int,
    gate: LiveActivationGate | None = None,
) -> tuple[bool, str | None]:
    gate = gate or LiveActivationGate()
    if gate.require_completed_backtest and not has_completed_backtest:
        return False, "completed backtest required on this exact preset version"
    if paper_trade_count < gate.min_paper_trades:
        return False, (
            f"paper sample {paper_trade_count} < min_trades {gate.min_paper_trades}"
        )
    return True, None


# re-export for callers
__all__ = [
    "LiveActivationGate",
    "PresetOverlayViolation",
    "PresetRecord",
    "ProvenanceEntry",
    "ResolvedConfigView",
    "can_activate_live",
    "resolve_with_provenance",
    "validate_new_version_params",
]
