from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scalping.scanner.cooldowns import CooldownManager

T0 = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_not_active_when_never_set():
    cm = CooldownManager()
    assert cm.is_active("symbol", "BTCUSDT", T0) is False


def test_active_within_window():
    cm = CooldownManager()
    cm.set("symbol", "BTCUSDT", "RISK_LIMIT", T0 + timedelta(minutes=5))
    assert cm.is_active("symbol", "BTCUSDT", T0 + timedelta(minutes=1)) is True


def test_expires_after_until():
    cm = CooldownManager()
    cm.set("symbol", "BTCUSDT", "RISK_LIMIT", T0 + timedelta(minutes=5))
    assert cm.is_active("symbol", "BTCUSDT", T0 + timedelta(minutes=6)) is False


def test_expired_cooldown_removed_from_active_set():
    cm = CooldownManager()
    cm.set("symbol", "BTCUSDT", "RISK_LIMIT", T0 + timedelta(minutes=5))
    cm.is_active("symbol", "BTCUSDT", T0 + timedelta(minutes=6))  # triggers cleanup
    assert cm.active_cooldown("symbol", "BTCUSDT", T0 + timedelta(minutes=6)) is None


def test_scopes_are_independent():
    cm = CooldownManager()
    cm.set("symbol", "BTCUSDT", "X", T0 + timedelta(minutes=5))
    assert cm.is_active("class", "BTCUSDT", T0) is False


def test_clear_expired_returns_count():
    cm = CooldownManager()
    cm.set("symbol", "A", "X", T0 - timedelta(minutes=1))
    cm.set("symbol", "B", "X", T0 + timedelta(minutes=5))
    count = cm.clear_expired(T0)
    assert count == 1
    assert cm.is_active("symbol", "B", T0) is True


def test_api_reconnect_cooldown_helper():
    cm = CooldownManager()
    cd = cm.set_api_reconnect_cooldown("BTCUSDT", T0, duration_s=30.0)
    assert cd.reason == "API_RECONNECT"
    assert cm.is_active("symbol", "BTCUSDT", T0 + timedelta(seconds=10)) is True
    assert cm.is_active("symbol", "BTCUSDT", T0 + timedelta(seconds=31)) is False


def test_clear_removes_immediately():
    cm = CooldownManager()
    cm.set("symbol", "BTCUSDT", "X", T0 + timedelta(minutes=5))
    cm.clear("symbol", "BTCUSDT")
    assert cm.is_active("symbol", "BTCUSDT", T0) is False
