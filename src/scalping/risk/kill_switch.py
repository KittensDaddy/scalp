"""Asymmetric-auth kill switch.

PLAN_OF_ACTION.md §5: "Killing must be easy; un-killing must be hard."
`POST /control/kill-switch` requires the standard control token; `DELETE` requires a
**separate stronger token** (`dashboard_unkill_token`) that is not stored on the
dashboard host. The control token alone must never be sufficient to clear a kill.

State is persisted (`KillSwitchRow`) so a restart honors a prior hard kill
(PLAN §6b) — `load` must run before the trading loop starts accepting signals.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scalping.persistence.models import KillSwitchRow


class Unauthorized(Exception):
    pass


class KillSwitch:
    def __init__(self, *, control_token: str, unkill_token: str) -> None:
        if not control_token or not unkill_token:
            raise ValueError("control_token and unkill_token must both be set")
        if control_token == unkill_token:
            raise ValueError("control_token and unkill_token must differ")
        self._control_token = control_token
        self._unkill_token = unkill_token
        self._killed = False
        self._reason: str | None = None
        self._set_at: datetime | None = None

    @property
    def killed(self) -> bool:
        return self._killed

    def engage(self, token: str, reason: str) -> None:
        """POST — the easy path. Standard control token only."""
        if token != self._control_token:
            raise Unauthorized("invalid control token")
        self._killed = True
        self._reason = reason
        self._set_at = datetime.now(UTC)

    def clear(self, token: str) -> None:
        """DELETE — the hard path. Control token is explicitly NOT accepted here,
        even though it authorizes `engage`; only the separate unkill token clears."""
        if token == self._control_token:
            raise Unauthorized("control token cannot clear the kill switch")
        if token != self._unkill_token:
            raise Unauthorized("invalid unkill token")
        self._killed = False
        self._reason = None
        self._set_at = None

    def load_state(self, *, killed: bool, reason: str | None, set_at: datetime | None) -> None:
        """Restore persisted state at startup without requiring auth — this is a
        trusted internal call, not an API path."""
        self._killed = killed
        self._reason = reason
        self._set_at = set_at

    async def persist(self, session: AsyncSession) -> None:
        session.add(
            KillSwitchRow(
                killed=self._killed, reason=self._reason,
                set_at=self._set_at or datetime.now(UTC),
            )
        )

    @staticmethod
    async def load_latest(session: AsyncSession) -> tuple[bool, str | None, datetime | None]:
        stmt = select(KillSwitchRow).order_by(KillSwitchRow.id.desc()).limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False, None, None
        return row.killed, row.reason, row.set_at
