from __future__ import annotations

from datetime import UTC, datetime

from scalping.domain.models import Side
from scalping.execution.client_order_id import make_client_algo_id, make_client_order_id

T = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_same_inputs_produce_same_id():
    a = make_client_order_id(strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T)
    b = make_client_order_id(strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T)
    assert a == b


def test_different_attempt_produces_different_id():
    a = make_client_order_id(
        strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T, attempt=0
    )
    b = make_client_order_id(
        strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T, attempt=1
    )
    assert a != b


def test_different_symbol_produces_different_id():
    a = make_client_order_id(strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T)
    b = make_client_order_id(strategy_version="caems_v2", symbol="ETHUSDT", side=Side.LONG, signal_time=T)
    assert a != b


def test_algo_id_distinguishes_stop_from_tp():
    stop_id = make_client_algo_id(
        purpose="stop", strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T
    )
    tp_id = make_client_algo_id(
        purpose="tp", strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T
    )
    assert stop_id != tp_id


def test_algo_id_distinct_from_entry_id():
    entry_id = make_client_order_id(
        strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T
    )
    algo_id = make_client_algo_id(
        purpose="stop", strategy_version="caems_v2", symbol="BTCUSDT", side=Side.LONG, signal_time=T
    )
    assert entry_id != algo_id
