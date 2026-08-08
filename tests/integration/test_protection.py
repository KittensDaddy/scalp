from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from scalping.domain.models import Side
from scalping.execution.ports import AlgoAck
from scalping.execution.protection import (
    ProtectionTimeoutIncident,
    apply_breakeven_move,
    breakeven_move_allowed,
    compute_breakeven_stop,
    establish_protection,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class FastPort:
    async def place_stop(self, symbol, side, stop_price, quantity, client_algo_id):
        return AlgoAck(algo_id="stop-1", ack_time=NOW)

    async def place_take_profit(self, symbol, side, tp_price, quantity, client_algo_id):
        return AlgoAck(algo_id="tp-1", ack_time=NOW)

    async def amend_stop(self, symbol, client_algo_id, new_stop_price):
        self.amended = new_stop_price
        return AlgoAck(algo_id=client_algo_id, ack_time=NOW)


class SlowPort(FastPort):
    def __init__(self, delay_s: float):
        self.delay_s = delay_s

    async def place_stop(self, symbol, side, stop_price, quantity, client_algo_id):
        await asyncio.sleep(self.delay_s)
        return AlgoAck(algo_id="stop-1", ack_time=NOW)


class FailingPort(FastPort):
    async def place_take_profit(self, symbol, side, tp_price, quantity, client_algo_id):
        raise RuntimeError("exchange rejected")


async def test_protection_established_within_timeout():
    port = FastPort()
    result = await establish_protection(
        port=port, symbol="BTCUSDT", side=Side.LONG, quantity=1.0, stop_price=99.0,
        tp_price=101.0, fill_time=NOW, protection_timeout_ms=2000,
        client_algo_id_stop="stop-cid", client_algo_id_tp="tp-cid",
    )
    assert result.protected is True
    assert result.stop_algo_id == "stop-1"
    assert result.tp_algo_id == "tp-1"


async def test_protection_timeout_raises_incident():
    port = SlowPort(delay_s=0.05)
    with pytest.raises(ProtectionTimeoutIncident):
        await establish_protection(
            port=port, symbol="BTCUSDT", side=Side.LONG, quantity=1.0, stop_price=99.0,
            tp_price=101.0, fill_time=NOW, protection_timeout_ms=10,
            client_algo_id_stop="stop-cid", client_algo_id_tp="tp-cid",
        )


async def test_protection_failure_raises_incident():
    port = FailingPort()
    with pytest.raises(ProtectionTimeoutIncident):
        await establish_protection(
            port=port, symbol="BTCUSDT", side=Side.LONG, quantity=1.0, stop_price=99.0,
            tp_price=101.0, fill_time=NOW, protection_timeout_ms=2000,
            client_algo_id_stop="stop-cid", client_algo_id_tp="tp-cid",
        )


def test_compute_breakeven_stop_long():
    stop = compute_breakeven_stop(side=Side.LONG, entry_price=100.0, round_trip_cost_price_units=0.1)
    assert stop == 100.1


def test_compute_breakeven_stop_short():
    stop = compute_breakeven_stop(side=Side.SHORT, entry_price=100.0, round_trip_cost_price_units=0.1)
    assert stop == 99.9


def test_breakeven_move_allowed_when_improving_long():
    assert breakeven_move_allowed(side=Side.LONG, current_stop=99.0, new_stop=100.1, already_moved=False) is True


def test_breakeven_move_rejected_if_already_moved():
    assert breakeven_move_allowed(side=Side.LONG, current_stop=99.0, new_stop=100.1, already_moved=True) is False


def test_breakeven_move_rejected_if_it_would_loosen_long():
    # new_stop below current_stop would move the stop away from price for a long
    assert breakeven_move_allowed(side=Side.LONG, current_stop=99.5, new_stop=99.0, already_moved=False) is False


def test_breakeven_move_rejected_if_it_would_loosen_short():
    assert breakeven_move_allowed(side=Side.SHORT, current_stop=100.5, new_stop=101.0, already_moved=False) is False


async def test_apply_breakeven_move_amends_when_allowed():
    port = FastPort()
    new_stop = await apply_breakeven_move(
        port=port, symbol="BTCUSDT", side=Side.LONG, client_algo_id_stop="stop-cid",
        current_stop=99.0, entry_price=100.0, round_trip_cost_price_units=0.1, already_moved=False,
    )
    assert new_stop == pytest.approx(100.1)
    assert port.amended == pytest.approx(100.1)


async def test_apply_breakeven_move_noop_when_already_moved():
    port = FastPort()
    new_stop = await apply_breakeven_move(
        port=port, symbol="BTCUSDT", side=Side.LONG, client_algo_id_stop="stop-cid",
        current_stop=99.0, entry_price=100.0, round_trip_cost_price_units=0.1, already_moved=True,
    )
    assert new_stop is None
    assert not hasattr(port, "amended")
