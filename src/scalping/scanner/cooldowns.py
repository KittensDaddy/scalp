"""Cooldown manager — SCANNER_DASHBOARD_PLAN.md §B ("Cooldown manager (exists
partially? verify)") / §N Phase 4 (including the "API reconnect" cooldown).

Pure in-memory state machine: `(scope, key)` -> active cooldown until a timestamp.
Persistence (the `cooldowns` DB table, §H) is a thin repo layer beneath this,
loaded at startup and written on every `set`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Cooldown:
    scope: str  # "symbol" | "class" | "global"
    key: str  # symbol name, class name, or "*" for global
    reason: str
    until: datetime


class CooldownManager:
    def __init__(self) -> None:
        self._active: dict[tuple[str, str], Cooldown] = {}

    def set(self, scope: str, key: str, reason: str, until: datetime) -> None:
        self._active[(scope, key)] = Cooldown(scope, key, reason, until)

    def clear(self, scope: str, key: str) -> None:
        self._active.pop((scope, key), None)

    def is_active(self, scope: str, key: str, now: datetime) -> bool:
        cd = self._active.get((scope, key))
        if cd is None:
            return False
        if now >= cd.until:
            del self._active[(scope, key)]
            return False
        return True

    def active_cooldown(self, scope: str, key: str, now: datetime) -> Cooldown | None:
        if self.is_active(scope, key, now):
            return self._active[(scope, key)]
        return None

    def clear_expired(self, now: datetime) -> int:
        expired = [k for k, cd in self._active.items() if now >= cd.until]
        for k in expired:
            del self._active[k]
        return len(expired)

    def all_active(self, now: datetime) -> list[Cooldown]:
        self.clear_expired(now)
        return list(self._active.values())

    def set_api_reconnect_cooldown(
        self, symbol: str, now: datetime, duration_s: float = 30.0
    ) -> Cooldown:
        """PLAN_OF_ACTION.md §K: "Process restart: ... cooldown 'API reconnect'
        applied" — signals are suppressed on a symbol immediately after a
        reconnect/backfill until fresh data has had time to accumulate."""
        cd = Cooldown("symbol", symbol, "API_RECONNECT", now + timedelta(seconds=duration_s))
        self._active[("symbol", symbol)] = cd
        return cd
