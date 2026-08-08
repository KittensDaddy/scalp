from __future__ import annotations

import pytest

from scalping.risk.kill_switch import KillSwitch, Unauthorized


def _ks() -> KillSwitch:
    return KillSwitch(control_token="control-tok", unkill_token="unkill-tok")


def test_engage_with_control_token_succeeds():
    ks = _ks()
    ks.engage("control-tok", "manual test")
    assert ks.killed is True


def test_engage_with_wrong_token_raises():
    ks = _ks()
    with pytest.raises(Unauthorized):
        ks.engage("wrong", "x")
    assert ks.killed is False


def test_clear_with_control_token_alone_is_rejected():
    """The core asymmetry: the token that can kill must NOT be able to un-kill."""
    ks = _ks()
    ks.engage("control-tok", "manual test")
    with pytest.raises(Unauthorized):
        ks.clear("control-tok")
    assert ks.killed is True


def test_clear_with_unkill_token_succeeds():
    ks = _ks()
    ks.engage("control-tok", "manual test")
    ks.clear("unkill-tok")
    assert ks.killed is False


def test_clear_with_wrong_token_raises():
    ks = _ks()
    ks.engage("control-tok", "manual test")
    with pytest.raises(Unauthorized):
        ks.clear("garbage")
    assert ks.killed is True


def test_same_token_for_both_roles_rejected_at_construction():
    with pytest.raises(ValueError, match="must differ"):
        KillSwitch(control_token="same", unkill_token="same")


def test_load_state_restores_without_auth():
    ks = _ks()
    ks.load_state(killed=True, reason="restart recovery", set_at=None)
    assert ks.killed is True
