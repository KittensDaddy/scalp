"""Notification adapter interface + Telegram first — SCANNER_DASHBOARD_PLAN.md §S11."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AlertEvent:
    kind: str  # e.g. "score_threshold", "kill_switch", "protection_gap"
    symbol: str | None
    message: str
    payload: dict


@runtime_checkable
class NotificationPort(Protocol):
    async def send(self, event: AlertEvent) -> None: ...


class NullNotifier:
    """Default no-op adapter — used in tests and when Telegram is not configured."""

    def __init__(self) -> None:
        self.sent: list[AlertEvent] = []

    async def send(self, event: AlertEvent) -> None:
        self.sent.append(event)


class TelegramNotifier:
    """Thin Telegram Bot API adapter. Network I/O only; alert policy lives elsewhere."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        http_post,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._http_post = http_post  # async (url, json) -> None

    async def send(self, event: AlertEvent) -> None:
        text = f"[{event.kind}] {event.message}"
        if event.symbol:
            text = f"[{event.kind}] {event.symbol}: {event.message}"
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        await self._http_post(url, {"chat_id": self._chat_id, "text": text})


@dataclass(frozen=True)
class ScoreAlertRule:
    symbol: str
    min_score: float


class AlertEngine:
    """Fires once when a watchlist symbol crosses its score threshold upward."""

    def __init__(self, notifier: NotificationPort) -> None:
        self._notifier = notifier
        self._rules: list[ScoreAlertRule] = []
        self._armed: set[str] = set()  # symbols currently below threshold

    def set_rules(self, rules: list[ScoreAlertRule]) -> None:
        self._rules = list(rules)
        self._armed = {r.symbol for r in rules}

    async def on_score(self, symbol: str, score: float) -> None:
        for rule in self._rules:
            if rule.symbol != symbol:
                continue
            if score < rule.min_score:
                self._armed.add(symbol)
                return
            if symbol in self._armed and score >= rule.min_score:
                self._armed.discard(symbol)
                await self._notifier.send(
                    AlertEvent(
                        kind="score_threshold",
                        symbol=symbol,
                        message=f"score {score:.1f} ≥ {rule.min_score:.1f}",
                        payload={"score": score, "min_score": rule.min_score},
                    )
                )
