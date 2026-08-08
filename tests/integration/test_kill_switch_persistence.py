from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from scalping.persistence.engine import init_db, make_engine
from scalping.risk.kill_switch import KillSwitch


async def test_kill_state_survives_restart():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sessionmaker = async_sessionmaker(engine)

    ks1 = KillSwitch(control_token="ctrl", unkill_token="unkill")
    ks1.engage("ctrl", "forced restart drill")
    async with sessionmaker() as session:
        await ks1.persist(session)
        await session.commit()

    # simulate process restart: new KillSwitch instance, load from DB
    ks2 = KillSwitch(control_token="ctrl", unkill_token="unkill")
    async with sessionmaker() as session:
        killed, reason, set_at = await KillSwitch.load_latest(session)
    ks2.load_state(killed=killed, reason=reason, set_at=set_at)

    assert ks2.killed is True
    # and the control token still cannot clear it post-restart
    import pytest

    from scalping.risk.kill_switch import Unauthorized

    with pytest.raises(Unauthorized):
        ks2.clear("ctrl")

    ks2.clear("unkill")
    assert ks2.killed is False

    await engine.dispose()
