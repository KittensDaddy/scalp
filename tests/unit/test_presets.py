from __future__ import annotations

from pathlib import Path

import pytest

from scalping.config.frozen import FrozenStrategyError
from scalping.config.presets import (
    ClassPreset,
    PresetOverlayViolation,
    load_presets_yaml,
    resolve_effective_config,
)
from scalping.config.settings import EffectiveConfig

DOCS_PRESETS = Path(__file__).resolve().parents[2] / "DOCS" / "caems_presets.yaml"


def test_load_real_presets_yaml_parses_and_rejects_no_frozen_keys():
    presets = load_presets_yaml(DOCS_PRESETS)
    assert "btc" in presets
    assert "meme" in presets
    assert presets["btc"].values["strength_min"] == 0.20
    assert presets["meme"].disabled is False
    assert presets["new_listing"].disabled is True


def test_class_preset_overrides_defaults():
    defaults = EffectiveConfig()
    btc = ClassPreset(
        name="btc",
        values={"strength_min": 0.20, "spread_max_bps": 1.0, "risk_per_trade_pct": 0.15},
    )
    effective = resolve_effective_config(defaults, btc, overlays=[])
    assert effective.gates.spread_max_bps == 1.0
    assert effective.risk.risk_per_trade_pct == 0.15


def test_overlay_tighten_only_accepts_stricter_value():
    defaults = EffectiveConfig()
    base = ClassPreset(name="major_alt", values={"spread_max_bps": 1.8})
    overlay = ClassPreset(
        name="high_funding", overlay=True, values={"spread_max_bps": 1.0}
    )
    effective = resolve_effective_config(defaults, base, overlays=[overlay])
    assert effective.gates.spread_max_bps == 1.0


def test_overlay_loosening_is_rejected():
    defaults = EffectiveConfig()
    base = ClassPreset(name="major_alt", values={"spread_max_bps": 1.8})
    overlay = ClassPreset(
        name="high_funding", overlay=True, values={"spread_max_bps": 3.0}
    )
    with pytest.raises(PresetOverlayViolation):
        resolve_effective_config(defaults, base, overlays=[overlay])


def test_overlay_loosening_strength_min_is_rejected():
    # strength_min is TIGHTEN_UP: a *smaller* value is looser.
    defaults = EffectiveConfig()
    base = ClassPreset(name="meme", values={"strength_min": 0.30})
    overlay = ClassPreset(name="high_funding", overlay=True, values={"strength_min": 0.10})
    with pytest.raises(PresetOverlayViolation):
        resolve_effective_config(defaults, base, overlays=[overlay])


def test_frozen_key_in_class_preset_raises():
    defaults = EffectiveConfig()
    bad = ClassPreset(name="evil", values={"ema_fast_1m": 5})
    with pytest.raises(FrozenStrategyError):
        resolve_effective_config(defaults, bad, overlays=[])


def test_frozen_key_in_overlay_raises():
    defaults = EffectiveConfig()
    base = ClassPreset(name="btc", values={"spread_max_bps": 1.0})
    bad_overlay = ClassPreset(name="evil", overlay=True, values={"take_profit_r": 5.0})
    with pytest.raises(FrozenStrategyError):
        resolve_effective_config(defaults, base, overlays=[bad_overlay])


def test_frozen_key_in_per_symbol_override_raises():
    defaults = EffectiveConfig()
    base = ClassPreset(name="btc", values={"spread_max_bps": 1.0})
    with pytest.raises(FrozenStrategyError):
        resolve_effective_config(
            defaults, base, overlays=[], per_symbol_override={"time_stop_s": 1}
        )


def test_per_symbol_override_wins_over_everything():
    defaults = EffectiveConfig()
    base = ClassPreset(name="btc", values={"spread_max_bps": 1.0})
    overlay = ClassPreset(name="high_funding", overlay=True, values={"spread_max_bps": 0.9})
    effective = resolve_effective_config(
        defaults, base, overlays=[overlay], per_symbol_override={"spread_max_bps": 0.5}
    )
    assert effective.gates.spread_max_bps == 0.5


def test_all_docs_presets_resolve_without_error():
    """Every non-disabled class preset in the real yaml must resolve cleanly against
    defaults, proving the schema actually matches EffectiveConfig's fields."""
    presets = load_presets_yaml(DOCS_PRESETS)
    defaults = EffectiveConfig()
    overlays = [p for p in presets.values() if p.overlay]
    for preset in presets.values():
        if preset.overlay or preset.disabled:
            continue
        effective = resolve_effective_config(defaults, preset, overlays=[])
        assert effective.gates.strength_min == preset.values["strength_min"]

    # and overlays individually tighten-compatible against btc as a baseline
    btc = presets["btc"]
    for overlay in overlays:
        resolve_effective_config(defaults, btc, overlays=[overlay])
