"""L1 preset resolution + L6 live activation gates."""

from __future__ import annotations

import pytest

from scalping.config.frozen import FrozenStrategyError
from scalping.config.presets import ClassPreset
from scalping.config.settings import EffectiveConfig
from scalping.lab.presets import (
    can_activate_live,
    resolve_with_provenance,
    validate_new_version_params,
)


def test_resolve_with_provenance_marks_layers():
    defaults = EffectiveConfig()
    class_preset = ClassPreset(name="meme", values={"spread_max_bps": 3.0, "rvol_min": 2.0})
    view = resolve_with_provenance(defaults, class_preset, [])
    by_key = {p.key: p for p in view.provenance}
    assert by_key["spread_max_bps"].layer == "class_preset"
    assert by_key["spread_max_bps"].value == 3.0
    assert by_key["strength_min"].layer == "defaults"
    assert view.config.gates.spread_max_bps == 3.0


def test_validate_refuses_frozen_keys():
    with pytest.raises(FrozenStrategyError):
        validate_new_version_params({"ema_fast_1m": 10}, overlay=False, name="x")


def test_live_activation_gates():
    ok, reason = can_activate_live(has_completed_backtest=False, paper_trade_count=100)
    assert ok is False and "backtest" in (reason or "")
    ok, reason = can_activate_live(has_completed_backtest=True, paper_trade_count=10)
    assert ok is False and "paper sample" in (reason or "")
    ok, reason = can_activate_live(has_completed_backtest=True, paper_trade_count=50)
    assert ok is True and reason is None
