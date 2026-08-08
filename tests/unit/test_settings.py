from __future__ import annotations

import re

from scalping.config.settings import EffectiveConfig, Settings


def test_config_hash_deterministic():
    a = EffectiveConfig()
    b = EffectiveConfig()
    assert a.config_hash() == b.config_hash()


def test_config_hash_changes_with_value():
    a = EffectiveConfig()
    b = a.model_copy(deep=True)
    b.gates = b.gates.model_copy(update={"strength_min": 0.99})
    assert a.config_hash() != b.config_hash()


def test_config_hash_changes_with_frozen_version():
    a = EffectiveConfig()
    b = a.model_copy(deep=True)
    b.frozen = b.frozen.model_copy(update={"strategy_version": "caems_v3"})
    assert a.config_hash() != b.config_hash()


def test_settings_repr_never_leaks_secrets(monkeypatch):
    monkeypatch.setenv("SCALPING_BINANCE_API_KEY", "topsecretkey1234567890")
    monkeypatch.setenv("SCALPING_BINANCE_API_SECRET", "topsecretsecret1234567890")
    monkeypatch.setenv("SCALPING_CONTROL_TOKEN", "topsecrettoken1234567890")
    s = Settings()
    assert "topsecret" not in repr(s)
    assert "topsecret" not in str(s)


def test_frozen_params_not_settable_via_env(monkeypatch):
    # Frozen params live on their own model and are never read from env at all —
    # this documents the guarantee rather than testing pydantic internals.
    from scalping.config.frozen import FrozenParams

    assert "ema_fast_1m" not in Settings.model_fields
    fp = FrozenParams()
    assert fp.ema_fast_1m == 12
    try:
        fp.ema_fast_1m = 99  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "FrozenParams must be immutable"


def test_config_hash_is_hex_sha256():
    h = EffectiveConfig().config_hash()
    assert re.fullmatch(r"[0-9a-f]{64}", h)
