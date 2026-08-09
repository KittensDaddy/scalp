"""S11 notifications + score alerts."""

from __future__ import annotations

import pytest

from scalping.notifications.alerts import (
    AlertEngine,
    AlertEvent,
    NullNotifier,
    ScoreAlertRule,
    TelegramNotifier,
)


@pytest.mark.asyncio
async def test_score_alert_fires_on_threshold_cross():
    notifier = NullNotifier()
    engine = AlertEngine(notifier)
    engine.set_rules([ScoreAlertRule(symbol="SOLUSDT", min_score=80.0)])
    await engine.on_score("SOLUSDT", 70.0)  # arm
    await engine.on_score("SOLUSDT", 75.0)  # still below — stay armed
    assert notifier.sent == []
    await engine.on_score("SOLUSDT", 81.0)
    assert len(notifier.sent) == 1
    assert notifier.sent[0].kind == "score_threshold"
    # no re-fire until it drops below again
    await engine.on_score("SOLUSDT", 90.0)
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_telegram_notifier_posts_message():
    posted: list[tuple[str, dict]] = []

    async def fake_post(url: str, payload: dict) -> None:
        posted.append((url, payload))

    n = TelegramNotifier(bot_token="tok", chat_id="123", http_post=fake_post)
    await n.send(AlertEvent(kind="kill_switch", symbol=None, message="engaged", payload={}))
    assert "sendMessage" in posted[0][0]
    assert posted[0][1]["chat_id"] == "123"
    assert "engaged" in posted[0][1]["text"]
