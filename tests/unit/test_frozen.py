from __future__ import annotations

import pytest

from scalping.config.frozen import FrozenStrategyError, reject_frozen_keys


def test_reject_frozen_keys_raises_on_frozen_key():
    with pytest.raises(FrozenStrategyError):
        reject_frozen_keys({"ema_fast_1m": 10}, source="test")


def test_reject_frozen_keys_allows_non_frozen():
    reject_frozen_keys({"strength_min": 0.3, "rvol_min": 1.5}, source="test")


def test_reject_frozen_keys_message_names_source_and_key():
    with pytest.raises(FrozenStrategyError, match="preset:meme"):
        reject_frozen_keys({"take_profit_r": 2.0}, source="preset:meme")
